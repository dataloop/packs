#!/usr/bin/env python

import os
import sys
import time
import re
import psutil
import subprocess
import datetime
import StringIO

RATE_INTERVAL = 5


def _bytes_to_gb(num):
    return round(float(num) / 1024 / 1024 / 1024, 2)


def _get_counter_increment(before, after):
    value = after - before
    if value >= 0:
        return value
    for boundary in [1 << 16, 1 << 32, 1 << 64]:
        if (value + boundary) > 0:
            return value + boundary


def _string_to_float(num):
    non_decimal = re.compile(r'[^\d.]+')
    return round(float(non_decimal.sub('', num)), 2)


def exact_match(phrase, word):
    b = r'(\s|^|$)'
    res = re.match(b + word + b, phrase, flags=re.IGNORECASE)
    return bool(res)


def calculate_rate(present, past):
    try:
        return round((float(present) - float(past)) / RATE_INTERVAL, 2)
    except TypeError:
        return round((_string_to_float(present) - _string_to_float(past)) / RATE_INTERVAL, 2)


def check_memory():
    return {
        'memory': "%d%%" % int(psutil.virtual_memory().percent),
        'swap': "%d%%" % int(psutil.swap_memory().percent)
    }


def check_swap_rates():
    return {
        'swap_in': psutil.swap_memory().sin,
        'swap_out': psutil.swap_memory().sout
    }


def check_cpu():
    return {
        'cpu': "%d%%" % int(psutil.cpu_percent(interval=None))
    }


def check_load():
    cores = psutil.cpu_count()
    load_avg = {'load_1_min': 0}
    if os.name != 'nt':
        load = os.getloadavg()
        load_avg.update({
            'load_1_min': load[0],
            'load_5_min': load[1],
            'load_15_min': load[2]
        })

    load_avg['load_fractional'] = round(float(load_avg['load_1_min']) / int(cores), 2)
    return load_avg


def check_netio():
    # total net counters
    net_all = psutil.net_io_counters()._asdict()
    net_map = {'network.%s' % k: v for k, v in net_all.iteritems()}
    return net_map


def check_cputime():
    # total cpu counters
    cputime_all = psutil.cpu_times_percent()._asdict()
    cpu_map = {'cpu.%s' % k: v for k, v in cputime_all.iteritems()}
    cpu_map['cpu.cores'] = psutil.cpu_count(logical=True)
    return cpu_map


def check_diskio():
    dm = False
    disk_map = {}
    try:
        # total io counters
        diskio_all = psutil.disk_io_counters()._asdict()
        disk_map.update({"disk.%s" % k: v for k, v in diskio_all.iteritems()})

        return disk_map
    except RuntimeError:  # Windows needs disk stats turned on with 'diskperf -y'
        return {}


def check_virtmem():
    virtmem = psutil.virtual_memory()._asdict()
    virt_map = {'vmem.%s' % k: v for k, v in virtmem.iteritems()}
    virt_map.update({
        'vmem.total_gb': "%sGb" % _bytes_to_gb(virtmem['total']),
        'vmem.available_gb': "%sGb" % _bytes_to_gb(virtmem['available']),
        'vmem.used_gb': "%sGb" % _bytes_to_gb(virtmem['used'])
    })
    return virt_map


def check_uptime():
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    now_time = datetime.datetime.now()
    uptime = now_time - boot_time
    uptime_hours = (uptime.days * 24) + (uptime.seconds // 3600)
    return {'uptime.hours': uptime_hours}


def check_processes():
    process_map = {
        'processes.total': len(psutil.pids()),
        'processes.zombie': sum([1 for proc in psutil.process_iter() if proc.status() == psutil.STATUS_ZOMBIE])
    }
    return process_map


checks = [
    check_cpu,
    check_memory,
    check_swap_rates,
    check_load,
    check_cputime,
    check_netio,
    check_diskio,
    check_virtmem,
    check_processes,
    check_uptime
]

rates = [
    check_swap_rates,
    check_diskio,
    check_netio
]


past_output = {}
for check in checks:
    past_output.update(check())

time.sleep(RATE_INTERVAL)

present_output = {}
for check in rates:
    present_output.update(check())

raw_output = {}
for present_key, present_value in present_output.iteritems():
    if present_key in past_output:
        if 'per_sec' not in present_key:
            raw_output[present_key + '_per_sec'] = calculate_rate(present_value, past_output[present_key])

        if exact_match(present_key, 'network.bytes_sent'):
            raw_output['net_upload'] = str((_get_counter_increment(past_output[present_key], present_value)
                                            / 1024) / RATE_INTERVAL) + 'Kps'

        if exact_match(present_key, 'network.bytes_recv'):
            raw_output['net_download'] = str((_get_counter_increment(past_output[present_key], present_value)
                                              / 1024) / RATE_INTERVAL) + 'Kps'

raw_output.update(past_output)
raw_output.update(check_cpu())

buf = StringIO.StringIO()
buf.write('OK | ')
for key, val in raw_output.iteritems():
    buf.write('%s=%s;;;; ' % (key.lower(), val))
buf.write('count=1;;;; ')
buf.write('metrics=%d;;;; ' % len(raw_output.keys()))
buf.write('interval=%d;;;; ' % RATE_INTERVAL)
print buf.getvalue()

sys.exit(0)
