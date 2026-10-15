# Baseline harness design — draft, 2026-10-15

Goal: repeatable full-server runs of the unmodified Folia baseline (docs/TOOLCHAIN.md)
that later A/B runs reuse unchanged. Implements docs/BENCHMARK_PROTOCOL.md.

## World fixtures

- Synthetic only: a fixed seed and settings, generated once by the baseline jar,
  pre-generated over the test area, then archived as `.local/worlds/<name>.tar.zst`
  with its SHA-256. Every repetition restores from the archive; nothing reuses a
  world from a previous run.
- `city-1000`: 1,000 x 1,000 block flat or superflat area with scripted structures
  (roads, buildings, a redstone/block-entity district) placed by a datapack or
  structure files committed to the repo. No game-derived assets are committed.
- `dispersed`: default terrain, players spread over about 8,000 x 8,000.
- Server config (`server.properties`, Paper/Folia YAML) lives in `harness/config/`
  and is copied fresh per run. offline-mode on a closed local network only.

## Clients

- Mineflayer 4.39.0 (Node.js 24.22.0, project-local) headless bots, offline-mode
  auth, one process per ~50 bots. Mineflayer has no 26.2 data, so the harness
  targets the Folia 26.1.2 baseline (docs/TOOLCHAIN.md).
- Each bot follows a seeded script: walk waypoints, place/break blocks, attack mobs,
  chat at a fixed rate. Bots log attempted vs. completed actions with timestamps,
  so lag-induced divergence shows up in the data.
- Ramp: 50 → 100 → 250 → 500 on this host; larger counts need remote generators.
- Bots run on separate cores from the server (taskset/affinity), recorded per run.

## Run sequence

1. Record host state: PSI, load, temperatures (`scripts/pressure-monitor.py`).
2. Restore world, copy config, start server with frozen JVM args; wait for "Done".
3. Connect bots in a fixed ramp; warm up (duration fixed after calibration).
4. Measure: Folia region tick times (median/p95/p99/max), TPS per region, JFR
   (GC, allocations, CPU), process CPU/RSS, network bytes, disconnects, bot
   action latency.
5. Stop bots, save-all, stop server; check the persistence round-trip on restart.
6. Write raw results to `.local/runs/<timestamp>/` (ignored) plus a sanitized
   summary JSON suitable for publication.

## Noise calibration (before any optimization)

- Idle-server and 50-bot runs, at least 5 repetitions each, on different days
  and times of day. Report coefficient of variation per metric; set the
  "beyond noise" threshold and warmup/measurement durations from these numbers.
- Freeze durations, JVM args, and pressure abort thresholds once calibrated.

## Recording and replay (separate from measurement)

Goal: every benchmark run can later be watched from any angle in ReplayMod, and
rendered as fixed-camera footage of chosen areas, without rendering during the run.

1. **Capture during the run, render nothing.** One passive *recorder* client
   (protocol-level, spectator mode, high view distance positioned over the test
   area) joins every run, measured or not, so A and B carry identical overhead.
   It writes every packet it receives, with timestamps, to disk. Those packets
   already contain the full world state (chunks, block changes) and every
   player's/entity's position, movement, animation and action. Cost: one extra
   connection plus sequential disk writes; no graphics. Several recorders can
   tile a 1,000 x 1,000 area if one view distance can't cover it.
2. **Store as ReplayMod `.mcpr`.** `.mcpr` is a zip of a timestamped packet stream
   (`recording.tmcpr`) plus `metaData.json` (MC/protocol version, duration,
   players). Writing that format directly means ReplayMod opens the recording
   natively; no live server is needed at playback time.
3. **Bot-side action logs** (bots already record attempted/completed actions)
   give a plain-text index of what happened and when, used to pick moments and
   areas to film and for the top-down map video.
4. **Playback later, on any machine:** open the `.mcpr` in a real client with
   ReplayMod: free camera, keyframed camera paths, and its renderer for
   fixed-angle footage of specific areas. A script can generate camera-path
   keyframes for a list of areas and times.

Why packet capture rather than re-executing the actions on a server: a re-run
would diverge (mob AI, RNG, tick timing, region scheduling), so it would not show
what actually happened. A packet capture is exact.

## Implemented (2026-10-15)

- `harness/world/build_city.py`: deterministic `city-1000` (seed 5000) built on the
  vanilla 26.1.2 jar over RCON; `layout.json` lists every building, park, redstone
  clock and hopper loop. `harness/world/render_map.py` draws a top-down map from the
  saved region files.
- `harness/run.py prepare-world`: Chunky pregeneration (radius 640) on the Folia jar,
  then a `.tar.gz` archive plus manifest with SHA-256s.
- `harness/telemetry`: TickTelemetry plugin (build with `build.sh SERVER_DIR`).
  Copies every completed region tick out of Folia's own 5 s tick window once per
  second on a background thread: `ticks.csv` (scheduled/start/end ns, CPU ns) and
  `regions.csv` (per-second region centre, chunks, players, entities, wall-clock anchor).
- `harness/bots/recorder.js`: camera recorder, ReplayMod `.mcpr` (format 14).
  `harness/bots/swarm.js`: seeded bots, JSONL action log with latencies.
- `harness/run.py run`: restore world, start server, cameras (`harness/cameras/*.json`),
  mobs, swarm, warmup, measure, collect, `summary.json`.
- `harness/video/overlay.py`: burns per-tick metrics for the region nearest the camera
  into a ReplayMod render (top-left, colour by tick time: green < 40 ms, yellow < 50,
  red over budget). Pass the replay timestamp the render starts at.

First smoke run (10 bots, 50 animals, 1 camera, 40 s measured; not a calibrated
baseline): 20.0 TPS, one region, median region tick 8.5 ms, p99 12.8 ms. All bots'
view areas overlapped, so Folia merged the whole city into a single region.

Known bot-script gaps: naive steering times out at walls; mobs too sparse for attacks;
some block placements refused. Fix before noise calibration.

## Open items

- Verify a recorder `.mcpr` opens in ReplayMod 26.1 (Fabric) — owner check.

- ReplayMod: available for 26.1 on Fabric (owner-confirmed).
- Region tick telemetry source: Folia's `/tps` and region profiler, or JFR events.
- Input latency measurement method (bot-side action→ack round trip).
