# Folia 26.1.2 player-count scaling baseline

**Aborted during the 100-player ramp on host CPU PSI.** One 50-player run is
valid under the declared rules; the requested three-repetition scaling curve was
not completed. No quadratic coefficients, fit quality, 50 ms extrapolation or
Folia capacity limit can be supported by this dataset. No further workloads
were started after the abort.

## Method

Unmodified Folia, pinned at `62dc0f257a4f5de1ef2eae8cf1627156a769c67f`,
Minecraft 26.1.2 / protocol 775. Every run restores the same synthetic city archive
and starts a fresh JVM. No upstream sources or world archives are edited.

The planned matrix uses 50, 100, 250 and 500 workload bots, three repetitions,
180 s warmup after joining/setup and 300 s measurement. Order rotates:
`50,100,250,500 / 100,250,500,50 / 250,500,50,100`.
If 500 is generator-limited, one additional 375-bot run is inserted.
Only one server runs at a time, checked through both fixed harness ports.

All runs use centre (16,16), spread ±80 blocks (160 × 160), 100 initially added
animals, seed 1, view/simulation distance 10, and the default spectator recorder
at (16,60,16), yaw 0°, pitch 90°. Existing seeded movement, block placement,
breaking, mob attacks and chat are preserved. Animals can die and placed blocks
can change: this is an evolving workload, not a stationary entity-count fixture.
The recorder contributes one additional connection and its traffic is included.

The JVM uses `-Xms6G -Xmx6G -XX:+UseG1GC -XX:+AlwaysPreTouch`.
CPU/memory caps are owner-suspended; execution is direct, with taskset affinity.
Topology inspection found SMT pairs `(0,6),(1,7),(2,8),(3,9),(4,10),(5,11)`.
The server uses `0-2,6-8`; bots and recorder use `3-5,9-11`: three complete
physical cores per side. The literal CLI defaults in `run.py`, `0-5` / `6-11`,
would share physical cores; the scaling runner overrides them deliberately.
Affinity does not reserve these cores against unrelated hosted services.

The retry matrix uses ten bots per Node shard (the run CLI supports at most 50).
Global index offsets preserve the seed formula `seed*100003 + global_index`; distinct shard prefixes make names unique.
Initial positions are precomputed by global bot index so join order does not
change their RNG assignment. Connections interleave shards at an aggregate
nominal spacing of 250 ms.
Each shard writes its own action and one-second event-loop health logs.

The initial 50-bot shard was retained as a diagnostic after sustained generator
lag appeared. Its scheduler was paused while its measurement finished, then
terminated after server shutdown. A separate retry matrix used ten-bot shards
and precomputed placement; different frozen inputs are not pooled. Both attempts
used the same 180/300 s durations. The retry stopped during its next (100-bot) run.

## Validity and analysis

PSI invalidation retains calibration's CPU some avg10 >20% or memory >5% for
at least ten seconds. A background watcher also aborts the workload and matrix
on these conditions, or I/O PSI >30% for ten seconds, throughout setup, warmup
and measurement. This is deliberately conservative on a shared host.

Generator event-loop p99 >100 ms for a continuous sequence spanning at least ten
seconds invalidates a run as `generator-limited`. Gaps >2.5 s break sustained
sequences; missing health coverage (edge >2.5 s or internal gap >3 s) independently
invalidates. Fewer than 95% of workload bots joining also means generator-limited.
Lifecycle events during measurement, missing telemetry, nonzero generator/runner
exit, changed TCP connections and mixed frozen inputs remain explicit failures.
Invalid attempts are retained and excluded from fits and valid-run averages.

TCP payload bytes are measured using server-side `ss -tinH` counters at both
measurement boundaries, preferring bytes_sent and falling back to bytes_acked.
Bytes/player/tick divides bytes/s by the requested workload-player count and
observed region TPS. These are application TCP payload bytes including the camera,
not Ethernet wire bytes; TCP framing, retransmission and local-loopback effects limit interpretation.

The planned first repetition per size invokes `profiler world 16 16 60 100`
over RCON sixty seconds into measurement. The command auto-stops after sixty seconds. Its text
output is retained locally. Phase shares use raw phase milliseconds divided by
Full Tick milliseconds. Nested phases overlap (entity tracker is inside chunk
source); packet encoding/Netty work outside the region tick is not timed here.
The profiled repetition remains identified because instrumentation adds overhead.

Tick medians, p95/p99/max and TPS reuse raw telemetry and calibration's wall-clock
mapping and percentile convention. Reported per-size values weight repetitions
equally. Action failures are fail/(done+fail), including failed terminal actions;
these client script timings are not uniform server acknowledgement latency.
Drift compares the first and last thirty measured seconds and also records five
one-minute medians. A longer measurement does not itself prove stationarity.

Quadratic ordinary least squares fits independent valid repetition values to
`a+bP+cP²`, using scaled predictors for numerical conditioning. R² and RMSE are
descriptive; fitting four sizes does not establish asymptotic complexity. Any
50 ms median crossing is an extrapolation from at most 500 bots on one desktop
host, not a capacity claim. Sustained 20 TPS, tail latency, generator validity
and correctness remain separate requirements.

Raw runs, recordings, source snapshots, hashes and manifests remain ignored under
`.local/`. Only reviewed aggregate results belong in this document.

## Frozen artifacts and provenance

| Parameter | Value |
| --- | --- |
| Paper ref | `b4682bfef616ac62e73cc96046dacdf4a6f53eeb` |
| JDK | Temurin 25.0.4.1+1, Linux x64 |
| Node / Mineflayer | 24.22.0 / 4.39.0, locked dependencies |
| Telemetry | TickTelemetry only; Chunky absent |
| Authentication | Offline, local loopback only |
| Host class | Ryzen 5 9600X, 6 cores / 12 logical CPUs, shared desktop |
| Thread settings | Upstream generated defaults, `threaded-regions.threads: -1`; one observed region |

SHA-256 values were recorded before execution; the jar and archive were checked
again after the abort and match. Upstream remains clean and unmodified.

| Input | SHA-256 |
| --- | --- |
| Server jar | `8057a60e002ae33ff24a95101d509a3ef597acd38511ae87e5df9353faea03ef` |
| World archive | `bae058c64f0fb63db428717acd45f729a2b4ede7aa535212c09ab48b56c4729d` |
| TickTelemetry jar | `7a3f5b3b0e8925fb82c4a6c6a20ee4772942817b5ecf8190bba3a2e6bfe80044` |
| harness/run.py | `0f2c7908b290c87320417597fc02404de8f6de985a02bebfb6cf9235a85303a5` |
| harness/calibrate.py | `051ee4fdd84e951ab61122cf56aaee863d7205a166d4fb58647c783d18fa0f98` |
| harness/scaling.py | `60742652c81af0c78f6843ce306f1de3465f64a625677e65f799fd867c50ae15` |
| harness/bots/swarm.js | `1fbfcfe98ab7d8ea6bc1a663c8828b7b9c54425ccfa115c052d916d96ac2d9ca` |
| harness/bots/recorder.js | `874d0ec152d4fd06885fef15e6e3a0d320878b2821745d9626db031188e96e9d` |
| harness/bots/package-lock.json | `896299ca538aa9b86053a485bb7cdca99a7914dea7a0124e1bc8b42c12e8f051` |
| scripts/pressure-monitor.py | `08b45e06a3074016df855c933d16c3ab397d956239dbd5260b48d0cd744c41fb` |

The measurement manifest and source copies are local under
`.local/scaling/20261015-194931/`; the earlier diagnostic manifest/source copies
are under `.local/scaling/20261015-194020/`. Re-analysis is under
`.local/scaling/reanalysis-final/`, and the separate diagnostic analysis under
`.local/scaling/diagnostic-50shard/`. Raw logs, connection endpoints and recordings
are ignored and are not reproduced here.

Post-run fixes recover joins from action logs after interrupted ramps, preserve
failure metadata with truncated logs, avoid analyzing nonexistent measurement
windows, and prevent further connections after a shard receives its stop signal.
They do not change the valid 50-player metrics or pressure abort. Independent
re-analysis with the final sources reproduces the entire final results JSON.
Final source hashes (measurement hashes above remain unchanged):

| Source | SHA-256 |
| --- | --- |
| harness/run.py | `4fb832c7fea227d23c1edcb175877483ceaa740aa096bc48133e0a949788ba0f` |
| harness/calibrate.py | `54818f8393998b7ccdd305d48132e04718f2477e53bbb22eb1d66b2413b51ff5` |
| harness/scaling.py | `a4ffddd09642913bc95319566b425e7aa802021283c570b904178e3c155ffa78` |
| harness/bots/swarm.js | `9adb3939891100cd021c2eb3e05c91867b2c60425e5e86c7567c9ec35e848d82` |
| harness/test_scaling.py | `8518999e7c37f16e25aa1324fa8faabf19ed177bbc037a443f47cd5b4106b0d6` |

Planned invocation (execution stopped on PSI as described above):

```sh
python3 -I -u harness/scaling.py run --shard-size 10 \
  --server-cpus 0-2,6-8 --client-cpus 3-5,9-11 \
  --warmup 180 --duration 300 --repetitions 3
```

## Measured results

Values below describe one valid repetition, not three-repetition means or
uncertainty estimates. Each complete measurement contains 6,000 regional ticks.
The valid run measured 51 clients (50 workload bots plus camera), one region,
and 243–269 total entities (mean 257.66) in per-second region snapshots.

| Requested bots | Valid / attempted retry runs | Tick median / p95 / p99 / max (ms) | Region TPS | Ticks >50 ms | MB/s | Bytes/player/tick |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 50 | 1 / 1 | 6.0126 / 7.7256 / 11.1107 / 45.5904 | 19.99987 | 0 / 6,000 (0%) | 0.670843 | 670.848 |
| 100 | 0 / 1 | —; aborted before measurement | — | — | — | — |
| 250 | 0 / 0 | Not attempted after abort | — | — | — | — |
| 500 | 0 / 0 | Not attempted after abort | — | — | — | — |

The valid 50-bot rate is 670,843.09 bytes/s over the TCP boundary interval;
51 connections are present at both boundaries. Bytes/player/tick uses the
observed 19.99987 TPS. The camera's bytes remain in the numerator. The fallback
375-bot run was not attempted: 500 was never reached, and host PSI had already
required stopping. The largest measured valid size is **50 workload bots**, with
only **one** valid repetition; this is not an accepted capacity or promotion gate.

### Actions at 50 bots

Terminal events inside measurement, equally including successful and failed
actions for latency percentiles. Pending attempts are not in the denominator.

| Action | Done | Failed | Failure rate (%) | p50 script duration (ms) |
| --- | ---: | ---: | ---: | ---: |
| walk | 234 | 501 | 68.163 | 20000.0 |
| place | 210 | 6 | 2.778 | 564.3 |
| break | 114 | 18 | 13.636 | 6.4 |
| attack | 86 | 53 | 38.129 | 1732.9 |
| chat | 101 | 0 | 0.000 | 1.4 |

Walks frequently reach the script's 20 s path timeout. These failures and attack
navigation failures cannot be assigned wholly to server latency; the workload's
pathfinder, world evolution and intermittent generator stalls also contribute.
This is scripted bot traffic, not a demonstration of equivalent human gameplay.

### Generator health

The valid run passes the predeclared ten-second sustained rule, **not** a rule
that forbids every individual stall. It still has intermittent generator delay.

| Shard | Bots | Health samples | Mean one-second p99 (ms) | Max one-second p99 (ms) | Samples p99 >100 ms (%) | Longest continuous span (s) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 10 | 296 | 43.25 | 384.04 | 7.77 | 8.531 |
| 1 | 10 | 300 | 21.80 | 131.60 | 0.33 | 0.000 |
| 2 | 10 | 297 | 36.10 | 310.12 | 4.71 | 8.560 |
| 3 | 10 | 295 | 49.62 | 351.80 | 16.27 | 9.003 |
| 4 | 10 | 298 | 34.34 | 359.92 | 2.68 | 8.347 |

The original single 50-bot process had p99 >100 ms in **54.24%** of its 271
measured health samples, with an **18.383 s** continuous span and **627.05 ms**
maximum. It is generator-limited and excluded. CPU PSI remained low in that
attempt (mean 0.453%, max 0.91%); the Node bottleneck must not be attributed to
Folia. The 100-bot retry logged 98 joined bots before host-pressure cleanup;
98% meets the join threshold, but there is no measurement to assess generator
health, throughput or server tick performance.

### Window drift and proposed durations

| Attempt | First 30 s median (ms) | Last 30 s median (ms) | Change | One-minute medians (ms) |
| --- | ---: | ---: | ---: | --- |
| 50, ten-bot shards, valid | 5.982358 | 5.781756 | -3.35% | 6.0085, 6.2515, 6.0138, 6.0444, 5.8097 |
| 50, fifty-bot shard, invalid diagnostic | 6.179699 | 5.374953 | -13.02% | 5.9551, 5.9897, 5.6826, 5.6269, 5.4285 |

Tick medians **still drift** after 180 s warmup: −3.35% in the only valid run,
and −13.02% in the invalid generator diagnostic. Minute two contains the 60 s
profile, so its elevation can include profiling overhead. The valid drift is
smaller than the earlier pilot's proposed 5% timing screen, but a single run and
changing entity/action populations cannot establish stationarity. The full
longer-duration calibration and per-size CV estimates remain unconfirmed.

### Phase profile

The console command works through RCON; no player sender or source modification
is required. It returns no immediate RCON text, but asynchronous server messages
and the completed profile files confirm execution. The 50-bot valid repetition
captured 60 s of region timing; no profile was collected at the larger sizes.
The diagnostic 50-bot profile is retained separately and excluded from results.

| Phase, valid 50 bots | Accumulated ms | Share of Full Tick (%) |
| --- | ---: | ---: |
| Entity Tick | 2186.762 | 28.2106 |
| Entity Tracker Tick | 1084.666 | 13.9929 |
| Chunk Source Tick | 4076.537 | 52.5898 |
| Tile Entity Tick | 1.917 | 0.0247 |
| Block Tick | 5.641 | 0.0728 |
| Fluid Tick | 1.554 | 0.0200 |
| Player Packet Processing | 579.651 | 7.4779 |
| Connection Tick | 505.621 | 6.5228 |

Full Tick denominator: **7,751.568 ms**. Chunk Source excluding Entity Tracker
is **38.5970%**. Player Packet Processing plus Connection Tick is **14.0007%**.
These inclusive phase shares must not be added indiscriminately. The profiler
does not isolate collision broad-phase/narrow-phase cost or asynchronous packet
encoding; Entity Tick is not a collision-specific measurement.

### Thermal, frequency and pressure observations

| Window | CPU PSI some avg10 mean / max (%) | Memory PSI mean / max (%) | I/O PSI mean / max (%) | Hottest exposed sensor (°C) |
| --- | --- | --- | --- | --- |
| Valid 50-bot measurement | 2.538 / 3.60 | 0 / 0 | 0.075 / 1.06 | 82.5–88.5 |
| Aborted 100-bot whole attempt | — / 32.50 | — / 0 | — / 0.73 | — / 89.1 |

The valid measurement has 293 host samples, maximum gap 2 s, and zero sustained
CPU/memory threshold breaches. The aborted ramp's host CSV spans 43 s and records
12 s continuously above 20% CPU PSI including cleanup; the live watcher triggered
at its ten-second limit. This is a host-pressure safety stop, not a measured
Folia TPS failure or proof that a particular hosted service failed.

Per-logical-CPU `/proc/cpuinfo` samples during the valid measurement:

| Allocation | Samples | Mean MHz | Min–max MHz |
| --- | ---: | ---: | --- |
| Server | 1,800 | 5,352.23 | 627.97–5,500.73 |
| Bots and recorder | 1,800 | 5,279.19 | 627.97–5,484.76 |

These are instantaneous frequency samples across busy and idle logical CPUs,
not residency-weighted frequency or throttling counters. The hottest sensor is
not established as a CPU package sensor. These readings do not establish the
absence of thermal throttling. After cleanup, both harness ports were closed
and CPU PSI some avg10 returned near zero (0.05%).

## Invalid attempts and problems

| Attempt | Outcome and reason |
| --- | --- |
| Six-bot smoke 1, two shards | Aborted on an action-file glob that also matched health logs; fixed and tested. No scaling result. |
| Six-bot smoke 2, two shards | Complete 5/10 s smoke, 3 s profiler; checked sharding, network, RCON profiling and cleanup. Not part of the scaling matrix. |
| Initial 50-bot diagnostic, one shard | Full 180/300 s run, invalid: generator p99 >100 ms for 18.383 s. |
| Retry 50 bots, five ten-bot shards | Valid by declared rules; one repetition only. |
| Retry 100 bots, ten ten-bot shards | Aborted during joins: CPU PSI >20% for ≥10 s. 98 logged joins. No warmup or measurement; runner exits 1. |
| Remaining repetitions, 250/500 and fallback 375 | Not run after host PSI abort. Missing results are not zero or successful runs. |

The invalid diagnostic's regional median/p95/p99/max were
5.7268 / 7.4451 / 8.9888 / 60.3225 ms, TPS 19.99987, 1/6,000 lagging ticks,
0.881322 MB/s and 881.328 bytes/player/tick. These are diagnostic aggregates,
**excluded from valid tables and fits**; a delayed generator changes server
load, so comparison with the valid run is not an optimization result.

An early-abort metadata issue originally left the 100-bot join count unset.
Re-analysis recovers 98 joins from retained shard action logs, avoiding a false
"fewer than 95% joined" generator label. New runs also save that count during
cleanup. The original metadata and first-pass analysis remain local; final
analysis retains the pressure error, runner exit and missing-window reasons.

## Fits and conclusions

| Requested model | Coefficients a,b,c | R² / RMSE | 50 ms median crossing |
| --- | --- | --- | --- |
| Regional tick median vs P | Not identifiable: one valid player count | Unavailable | Unavailable |
| Server bytes/s vs P | Not identifiable: one valid player count | Unavailable | Not applicable |

A quadratic needs at least three distinct valid sizes; repetition uncertainty
also needs completed repetitions. No invalid data or old ±40-block calibration
is substituted. There is therefore **no numerical extrapolation from ≤500 bots
on this desktop host**, and no demonstrated point where plain Folia stops
holding 20 TPS.

At 50 bots the largest requested inclusive phase is Chunk Source (52.59%),
followed by Entity Tick (28.21%); Entity Tracker contributes 13.99% of full tick
time. One size cannot establish an O(P²) coefficient or determine whether
tracking, packet encoding or collisions dominates that growth. Packet byte
volume is not encoding CPU time, and collision cost is not separately timed.

The first demonstrated limit here is the **local generator/host arrangement**:
a fifty-bot Node shard stalls, while ten-bot sharding improves responsiveness
but the 100-bot ramp triggers shared-host CPU pressure. A further curve needs
additional generator capacity and a PSI-safe allocation; no more local loads
were attempted. The longer warmup/measurement profile remains provisional.
No simulation changes, upstream builds, installations, commits or pushes occurred.

## Harness changes and checks

- `harness/run.py`: taskset CPU flags/validation and metadata; at-most-50-bot
  shards; unique prefixes/global seed offsets; interleaved connection ramp;
  global-index initial placement; separate/merged action logs; network boundary
  counters; timed RCON profiler capture and copied output; frequency samples;
  continuous PSI aborts; saved failure metadata, cleanup and aborted-join counts;
  lagging-tick share and first/last/minute tick medians.
- `harness/bots/swarm.js`: offset/spacing/start-delay arguments, per-second
  monitorEventLoopDelay p50/p99 logs, and signal handlers registered before the
  connect ramp so early stops flush logs; idempotent stop prevents additional
  connections during shutdown.
- `harness/calibrate.py`: optional scaling read mode, ≥95% join policy with
  action-log recovery, and runner-error retention; legacy calibration's exact
  join and scenario rules remain in its default mode.
- `harness/scaling.py`: rotated serial schedule, fixed parameters, source/tool
  fingerprints, incremental retained analysis, generator/network/profile
  validation, PSI matrix stop, conditional one-off 375 fallback, local STOP-file
  support, quadratic OLS, fit quality and threshold calculation.
- `harness/test_scaling.py`: synthetic tests for fit recovery/thresholds,
  invalid-run exclusion, duplicate rejection, sustained generator lag versus
  spikes/gaps/equality, TCP counter parsing/deltas/TPS normalization, profile
  denominator/nesting, tick drift/lagging share, shard-log selection and
  interrupted-ramp join recovery even with truncated tails.
- This report and the brief implementation-plan update record the partial result.

**14 unit tests pass**, including the six existing calibration tests. Python
compilation, Node syntax and `git diff --check` pass. No server benchmarks were
run after the PSI abort; re-analysis reads the retained local artifacts only.
