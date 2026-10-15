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

- Mineflayer (Node.js) headless bots, offline-mode auth, one process per ~50 bots.
  Needs a Node.js LTS install (owner approval pending).
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

## Open items

- Node.js approval; Mineflayer and protocol support for MC 26.2 (unverified).
- Region tick telemetry source: Folia's `/tps` and region profiler, or JFR events.
- Input latency measurement method (bot-side action→ack round trip).
