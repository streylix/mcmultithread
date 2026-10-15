# Folia 26.1.2 baseline noise calibration — 2026-10-15

This full-server matrix measures repeatability of the unmodified Folia baseline.
All ten runs completed valid; it is not an optimization comparison or capacity claim.

## Method and frozen inputs

`python3 -I -u harness/calibrate.py run` runs five repetitions per scenario in
the order idle, crowd50, idle, crowd50, and so on. Each run restores the same
synthetic `city-1000.tar.gz`, starts a fresh JVM, connects the recorder and clients,
waits 60 seconds after joining/setup, then measures for 120 seconds. Startup,
restoration, connection ramp, warmup and shutdown are outside measurement.

| Parameter | Value |
| --- | --- |
| Baseline Folia commit | `62dc0f257a4f5de1ef2eae8cf1627156a769c67f` |
| Paper ref | `b4682bfef616ac62e73cc96046dacdf4a6f53eeb` |
| Minecraft / protocol | 26.1.2 / 775 |
| JDK | Temurin 25.0.4.1+1, Linux x64 |
| JVM arguments | `-Xms6G -Xmx6G -XX:+UseG1GC -XX:+AlwaysPreTouch` |
| Node / Mineflayer | 24.22.0 / 4.39.0, locked dependencies |
| Idle | 0 workload bots, 0 added mobs, 1 default recorder |
| crowd50 | 50 workload bots, 100 added animals, 1 default recorder |
| Placement | Centre (16,16), spread ±40 blocks on both axes, seed 1 |
| Recorder | Spectator at (16,60,16), yaw 0°, pitch 90° |
| View / simulation distance | 10 / 10 chunks |
| Client authentication | Offline, local loopback server |
| Resource policy | Owner-suspended CPU/memory caps; direct execution, no affinity partition |

The jar and world SHA-256 values are taken from each completed run's `meta.json`:

- Jar (`folia-paperclip-26.1.2.local-SNAPSHOT.jar`):
  `8057a60e002ae33ff24a95101d509a3ef597acd38511ae87e5df9353faea03ef`
- World (`city-1000.tar.gz`):
  `bae058c64f0fb63db428717acd45f729a2b4ede7aa535212c09ab48b56c4729d`

The upstream checkout is read-only for this task. The world archive is never
rewritten. TickTelemetry is the only measurement plugin; Chunky is absent during
measurement. The camera and local bot generator contribute identical overhead
within each scenario. Bots use the existing seeded movement, placement, break,
attack and chat script; mob deaths and block changes evolve during each run.

## Measurement and validity

`calibrate.py` records `/proc/pressure/{cpu,memory,io}` immediately before each
run. It reads `host.csv` samples inside the actual measurement timestamps and
invalidates a run when CPU PSI **some avg10 >20%**, or memory PSI **some avg10 >5%**,
persists across a sequence spanning at least **10 seconds**. Samples are about
one second apart; a gap greater than two seconds breaks a sustained sequence.
Equality to a threshold is allowed. These are invalidation rules, not new host
admission limits or abort controls.

Missing pressure coverage (edge gap >2 seconds or internal gap >3 seconds),
missing telemetry, incomplete joins, measurement duration error >2 seconds,
measurement-time bot lifecycle errors/disconnects, or nonzero runner exit also
invalidate a run. Invalid runs remain in `calibration.json` with their metrics
and explicit reasons. No replacement runs are silently inserted. Runs with
different frozen inputs cannot be pooled. Old runs without spread metadata
retain that unknown value rather than inferring it from their labels.

The analyzer maps telemetry's monotonic timestamps to wall time with the nearest
per-second anchor. It uses the existing harness's nearest-rank-style percentile
selection (`round(p × (n−1))`). Each repetition contributes one value per metric;
the table reports the mean, sample standard deviation (`ddof=1`), coefficient of
variation (SD/|mean|), minimum and maximum across **valid repetitions**, without
pooling all ticks or weighting repetitions by action counts. Region TPS is the
mean of each observed region's tick count divided by the measured seconds.

Action p50 includes both successful and failed terminal events timestamped in
measurement, including actions attempted before measurement. Failure rate is
`fail / (done + fail)`, separately for each action and repetition. Attempts still
pending at the end do not enter this denominator. Raw attempt/completion logs
remain available locally. These client script durations include navigation,
timeouts and client work; attack measures packet submission, not a server damage
acknowledgement. They are not uniform server input-to-ack latency measurements.
Idle action metrics are absent, not zero. CV is undefined for zero means or fewer
than two valid values; all-zero failure rates need absolute limits instead.

Raw runs, PSI snapshots, recordings, tool/source hashes and the calibration
manifest stay ignored under `.local/`. Re-analyze any matching set with:

```sh
python3 -I harness/calibrate.py analyze .local/runs/<run-one> .local/runs/<run-two>
```

`--repetitions`, `--warmup` and `--duration` configure new matrices. Both subcommands
accept `--cpu-psi`, `--memory-psi`, `--sustained-seconds` and a new `--out` directory
under `.local/calibration/`. Defaults are five repetitions, 60/120 seconds and
20%/5%/10 seconds. Raw JSON uses failure-rate fractions and fractional CV.

## Results

The ten-run matrix measured on 2026-10-15, between 22:26:14 and 23:00:31 UTC (including
setup and warmup before each measurement). Every scenario has five valid repetitions.
All ten runs observed one region and all 50 crowd bots joined. Each idle run completed
with an empty action log and no swarm process. No replacement runs were needed.

Local provenance: `.local/calibration/20261015-182614/calibration.json`, with its
manifest, PSI snapshots and source/tool fingerprints. Every run's metadata agrees on the
jar/world hashes above.

### idle: 5/5 valid repetitions

| Metric | Mean | Sample SD | CV (%) | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Region tick median (ms) | 0.564815 | 0.0130599 | 2.31224 | 0.551613 | 0.582054 |
| Region tick p95 (ms) | 0.836359 | 0.0141148 | 1.68765 | 0.816875 | 0.850935 |
| Region tick p99 (ms) | 0.96445 | 0.0124473 | 1.29061 | 0.945256 | 0.978367 |
| Region tick max (ms) | 1.83589 | 0.557641 | 30.3744 | 1.15408 | 2.5032 |
| Global tick median (ms) | 0.014978 | 0.00216466 | 14.4523 | 0.01276 | 0.01725 |
| Region TPS | 19.9979 | 0.00330288 | 0.0165161 | 19.9932 | 20.0005 |

### crowd50: 5/5 valid repetitions

| Metric | Mean | Sample SD | CV (%) | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Region tick median (ms) | 5.06015 | 0.028563 | 0.56447 | 5.01668 | 5.0901 |
| Region tick p95 (ms) | 6.85314 | 0.0257425 | 0.37563 | 6.8338 | 6.89136 |
| Region tick p99 (ms) | 8.14686 | 0.16906 | 2.07516 | 7.9997 | 8.38392 |
| Region tick max (ms) | 27.8533 | 4.69151 | 16.8437 | 24.6388 | 36.0291 |
| Global tick median (ms) | 0.0144162 | 0.00237703 | 16.4886 | 0.01281 | 0.018431 |
| Region TPS | 19.9987 | 0.00297919 | 0.0148969 | 19.9933 | 20 |
| walk p50 latency (ms) | 10662.1 | 818.184 | 7.67376 | 9400.2 | 11516.4 |
| walk failure rate (%) | 35.7886 | 3.20514 | 8.95577 | 31.0513 | 39.5288 |
| place p50 latency (ms) | 562.2 | 8.08888 | 1.43879 | 549.1 | 571 |
| place failure rate (%) | 4.23454 | 1.19731 | 28.2749 | 2.34375 | 5.51181 |
| break p50 latency (ms) | 223.58 | 212.632 | 95.1031 | 18.8 | 502.2 |
| break failure rate (%) | 8.86065 | 4.01746 | 45.3405 | 6.25 | 15.942 |
| attack p50 latency (ms) | 623.48 | 134.193 | 21.5232 | 417.2 | 743.4 |
| attack failure rate (%) | 18.6357 | 4.76416 | 25.5647 | 11.1111 | 23.2877 |
| chat p50 latency (ms) | 4.7 | 1.38744 | 29.5201 | 3.2 | 6.1 |
| chat failure rate (%) | 0 | 0 | — | 0 | 0 |

### Host conditions

Measurement-window PSI is **some avg10**, in percent. Means in this host table pool the
one-second samples; performance tables above instead weight repetitions equally.

| Scenario | Host samples | CPU PSI mean / max | Memory PSI mean / max | I/O PSI mean / max | Hottest sensor range (°C) |
| --- | ---: | ---: | ---: | ---: | ---: |
| idle | 586 | 0.122 / 0.85 | 0.000 / 0.00 | 0.023 / 0.45 | 82.0–84.5 |
| crowd50 | 587 | 0.288 / 1.67 | 0.010 / 0.36 | 0.117 / 3.29 | 82.5–85.0 |

Before-run PSI ranges were cpu 0.00–0.36%, memory 0.00–0.10%, io 0.00–0.66%. No
measurement sample exceeded either calibration PSI threshold. The hottest exposed sensor
is not identified as a CPU package sensor; these readings do not establish absence of
frequency or thermal throttling. CPU frequency, per-process CPU/RSS, GC and throttling
counters are not supplied by this host CSV.

### Invalid runs

None: **10/10 valid**. Invalidity was checked from numeric PSI samples, not the
monitor's `breach` text (which uses different provisional thresholds). All attempted
runs remain in the raw JSON, including their validity/reason fields.

## Proposed beyond-noise screens

For tick times and action p50, use **max(5%, 3 × CV)**, rounded upward to a whole
percent. The 5% floor preserves the benchmark contract's initial practical-effect
hypothesis. For failure rates use **max(1 percentage point, 3 × sample SD)**, rounded
upward to 0.1 percentage point; CV is unhelpful near zero. For region TPS use
**max(0.020 TPS, 3 × sample SD)**, rounded upward to 0.001 TPS, as a regression screen
around the 20 TPS ceiling. The absolute floor covers measurement-boundary tick-count
quantization. Do not interpret a value slightly above 20 as an improvement.

| Scenario | Metric | Proposed change screen |
| --- | --- | ---: |
| idle | region_tick.median_ms | 7% |
| idle | region_tick.p95_ms | 6% |
| idle | region_tick.p99_ms | 5% |
| idle | region_tick.max_ms | 92% |
| idle | global_tick.median_ms | 44% |
| idle | region_tps_mean | 0.020 TPS (regression only) |
| crowd50 | region_tick.median_ms | 5% |
| crowd50 | region_tick.p95_ms | 5% |
| crowd50 | region_tick.p99_ms | 7% |
| crowd50 | region_tick.max_ms | 51% |
| crowd50 | global_tick.median_ms | 50% |
| crowd50 | region_tps_mean | 0.020 TPS (regression only) |
| crowd50 | actions.walk.p50_ms | 24% |
| crowd50 | actions.walk.fail_rate | 9.7 percentage points |
| crowd50 | actions.place.p50_ms | 5% |
| crowd50 | actions.place.fail_rate | 3.6 percentage points |
| crowd50 | actions.break.p50_ms | 286% |
| crowd50 | actions.break.fail_rate | 12.1 percentage points |
| crowd50 | actions.attack.p50_ms | 65% |
| crowd50 | actions.attack.fail_rate | 14.3 percentage points |
| crowd50 | actions.chat.p50_ms | 89% |
| crowd50 | actions.chat.fail_rate | 1.0 percentage points |

These are conservative exploratory effect-size screens for this **60/120 s profile**,
not confidence bounds or automatic promotion gates. Three SD is about 2.12 SD of the
difference between two independent single repetitions (whose variance doubles). With
only five repetitions, the estimated SD is uncertain; require repeated
paired/alternating A/B results, uncertainty intervals, correctness checks and regression
checks as well. Thresholds reaching/exceeding 100% cannot establish a timing reduction:
that metric is diagnostic until a new workload/measurement design reduces its noise.
Break p50 is particularly unstable because script durations mix immediate actions,
navigation and failures. Global tick times and chat p50 are tiny in absolute units,
despite large relative CV. Zero observed chat failures do not prove a zero underlying
rate; retain event counts and binomial uncertainty in comparisons.

## Proposed frozen durations

Propose **180 s warmup and 300 s measurement** for the next confirmed comparison
profile. The present default and completed calibration remain **60/120 s**; no run was
changed midway and these longer durations have not been calibrated.

For idle, the mean of the per-run regional medians in the first versus last 30 measured
seconds was 0.5993 → 0.5333 ms (-11.0%).

For crowd50, the mean of the per-run regional medians in the first versus last 30
measured seconds was 5.1626 → 4.9577 ms (-4.0%).

Most runs show settling and/or workload evolution after the initial 60-second warmup. A
180-second proposal puts measurement after the entire settling interval observed here;
300 seconds would collect about 2.5 times as many action outcomes at the same rate.
Neither is evidence that stationarity will follow. Confirm with another interleaved
matrix, check time-window trends and entity/action counts (longer warmup changes the
evolving world), then freeze the profile and re-estimate its CV thresholds. Until then,
comparisons reproducing this pilot must retain 60/120 seconds and its stated
limitations.

## Harness changes and checks

`run.py` skips starting the swarm for zero bots and creates an empty `actions.jsonl`;
the normal camera/warmup/measurement path stays active. It now records spread in
metadata and closes telemetry CSV streams explicitly when summarizing. `swarm.js`, Folia
source and the world archive were not changed. The calibration tests exercise sustained
PSI versus spikes, strict thresholds, measurement boundaries, missing coverage, sample
statistics, raw-telemetry re-analysis, invalid-run retention and duplicate/mixed-input
rejection. A second CLI analysis reproduces the recorded aggregates.

## Scope and follow-up

This first matrix samples one session on a shared host. It does not establish
day-to-day repeatability, controlled server/client core isolation, correctness
under replay, persistence round-trip equivalence or architecture promotion.
Repeat on other days/times before treating the thresholds as general host noise.
CPU optimization work still requires the benchmark contract's controlled A/B and
correctness evidence.
