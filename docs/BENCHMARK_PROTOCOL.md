# Benchmark contract — draft, requires baseline calibration

## Reproduction

Run baseline and candidate sequentially on the same host. Freeze exact commits,
artifact hashes, Java vendor/version, JVM arguments, CPU quota/affinity, memory
limits, configuration, protocol, world snapshot hash, bot script and seed.
Restore identical synthetic worlds for every repetition. Keep bots outside the
server core allocation; use external generators as scale warrants.

Warm the JVM and establish steady state before measurement. Use at least three
repetitions per build and alternate/randomize order. Choose and record warmup and
measurement durations during baseline calibration, then freeze them for A/B.
Record attempted and completed scripted actions so lag-induced divergence is visible.

## Scenarios and telemetry

Start with idle connections, dispersed SMP and a dense 1,000 x 1,000 city.
Add smaller crowds, PvP, mobs/pathfinding, collisions, redstone/block entities,
chunk loading and persistence. Increase connected clients gradually from about
50; workstation admission does not authorize large bot runs.

Measure regional tick median/p95/p99/max, sustained TPS and lagging regions,
input latency, disconnects, CPU/per-core use, throttling, queue/synchronization
cost, allocations/GC/memory, network and disk. Sample host PSI, background load,
thermal state and throttling before/during/after runs. Store raw telemetry locally;
publish only reviewed synthetic or sanitized aggregates.

## Admission and correctness

Default aggregate development cap: 200% CPU and 6 GiB, including native memory,
Gradle daemons and bots. Benchmark mode up to 400%/12 GiB requires explicit
approval and low host pressure. Define numerical pressure and thermal abort
thresholds during baseline calibration; until then no unattended benchmark admission.
Abort/invalidate runs affecting hosted services, with throttling or material noise;
record invalidation reasons rather than dropping inconvenient results.

Require no correctness failures, sustained 20 TPS at claimed capacity, no material
p99/stability regression and statistically supported gain beyond noise (initial
hypothesis 5%). Report uncertainty and unrelated workload regressions. Verify
state invariants, region-boundary interactions, replay scope, concurrency safety
and persistence/restarts. Microbenchmarks never substitute for full-server tests.
