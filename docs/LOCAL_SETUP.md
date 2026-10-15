# Local setup

Sandboxed commands cannot connect to the user systemd bus (operation not
permitted), and the cgroup filesystem is read-only. Changing environment variables
does not resolve this. Approved commands outside the sandbox can launch the
limited service. No host settings were changed.

Verified on 2026-10-15 through an approved launcher invocation: systemd reports
CPUQuotaPerSecUSec=2s, MemoryHigh=5368709120, MemoryMax=6442450944,
MemorySwapMax=0, with CPU and memory accounting enabled. The test ran only a
systemd property query and exited successfully. Direct cgroup-file verification
was unavailable through this environment's filesystem view; these values were
verified through the systemd manager instead.

From a normal terminal on the Linux host, in the project directory, verify:

```sh
systemctl --user is-system-running
bash scripts/limited-run.sh true
```

The second command starts only a trivial process, bounded by the development
limits. A successful terminal check does not grant the managed agent bus access;
builds can instead request approval to use the launcher outside the sandbox.
Do not substitute uncontained
execution or change system-wide permissions to bypass the restriction.

## Allocation

```sh
# Default: 200% CPU, 6 GiB aggregate memory.
bash scripts/limited-run.sh COMMAND ARGUMENTS

# Smaller allocation, same containment.
PROJECT5K_CPU_PERCENT=100 PROJECT5K_MEMORY_GIB=3 bash scripts/limited-run.sh COMMAND
```

CPU percent means logical-CPU equivalents (200% = two); it does not reserve cores.
Memory includes all descendants and JVM native overhead. Use one workload service
at a time. The shared fixed unit rejects overlapping profile launches. Larger
workstation allocations require updating the project policy first.

Benchmark mode is deliberately unavailable until host-pressure admission and
ongoing abort monitoring have been calibrated. Merely choosing a profile or
setting an approval environment variable is not permission to benchmark.

Next setup tasks: approve and provision a project-local JDK 25, verify its vendor
checksum, select and lock an exact reviewed Folia revision, and obtain its own
verified Gradle wrapper. No JDK or dependency downloads have happened yet.
