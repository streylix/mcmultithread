#!/usr/bin/env python3
"""Read-only, identifier-free readiness report. Does not admit workloads."""
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            memory[key] = int(value.split()[0])
    pressure = {}
    for resource in ('cpu', 'memory', 'io'):
        path = Path('/proc/pressure') / resource
        pressure[resource] = path.read_text().strip() if path.exists() else None
    manager = subprocess.run(
        ['systemctl', '--user', 'show-environment'], capture_output=True,
        timeout=5, check=False
    ) if shutil.which('systemctl') else None
    report = {
        'logical_cpus': os.cpu_count(),
        'affinity_cpus': len(os.sched_getaffinity(0)),
        'memory_kib': memory,
        'pressure': pressure,
        'free_storage_gib': round(shutil.disk_usage('.').free / 2**30, 1),
        'tools_on_path': {tool: bool(shutil.which(tool)) for tool in
                          ('java', 'javac', 'git', 'node', 'gitleaks', 'systemd-run')},
        'user_systemd_accessible': manager is not None and manager.returncode == 0,
        'workload_admitted': False,
    }
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
