#!/usr/bin/env bash
set -euo pipefail
# Resource guardrails are suspended by the owner (2026-10-15): run directly, in
# parallel, without cgroup limits. Set PROJECT5K_CONTAIN=1 to restore containment.
if [[ ${PROJECT5K_CONTAIN:-0} != 1 ]]; then
    [[ ${1:-} == --profile ]] && shift 2
    exec "$@"
fi
profile=development
if [[ ${1:-} == --profile ]]; then
    profile=${2:-}
    shift "$(( $# >= 2 ? 2 : 1 ))"
fi
case "$profile" in
    development) max_cpu=200; max_memory=6 ;;
    benchmark)
        if [[ ${PROJECT5K_BENCHMARK_APPROVED:-} != yes ]]; then
            echo 'Benchmark profile requires explicit approval; then set PROJECT5K_BENCHMARK_APPROVED=yes.' >&2
            exit 2
        fi
        max_cpu=400; max_memory=12 ;;
    *) echo 'Unknown profile; use development or benchmark.' >&2; exit 2 ;;
esac
cpu=${PROJECT5K_CPU_PERCENT:-$max_cpu}
memory=${PROJECT5K_MEMORY_GIB:-$max_memory}
if [[ ! $cpu =~ ^[1-9][0-9]{0,2}$ || ! $memory =~ ^[1-9][0-9]?$ ]]; then
    echo 'CPU percent and memory GiB must be positive integers.' >&2
    exit 2
fi
if (( cpu > max_cpu || memory > max_memory )); then
    echo "Requested limits exceed $profile maximum: ${max_cpu}% CPU / ${max_memory} GiB." >&2
    exit 2
fi
if (( $# == 0 )); then
    echo 'Usage: bash scripts/limited-run.sh [--profile development|benchmark] COMMAND [ARG ...]' >&2
    exit 2
fi
if ! command -v systemd-run >/dev/null || ! systemctl --user show-environment >/dev/null 2>&1; then
    echo 'Refusing workload: user systemd containment is unavailable.' >&2
    exit 1
fi
# A fixed unit name rejects overlapping project loads. Child processes stay in
# the service cgroup; service teardown kills remaining daemons as well.
if [[ $profile == benchmark ]]; then
    echo 'Benchmark admission pending: calibrated host-pressure monitoring is not implemented.' >&2
    exit 1
fi
# Every profile uses the same unit to prevent overlapping aggregate allocations.
exec systemd-run --user --unit=project5k-workload --wait --pipe --collect \
    --working-directory="$PWD" \
    -p "CPUQuota=${cpu}%" -p "MemoryHigh=$((memory * 1024 * 5 / 6))M" \
    -p "MemoryMax=${memory}G" -p MemorySwapMax=0 \
    -p CPUWeight=10 -p IOWeight=10 -p TasksMax=256 \
    -p KillMode=control-group -- "$@"
