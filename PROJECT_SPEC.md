# Project 5K — Technical Specification

**Status:** initial specification / research project. **Primary target:** 5,000 concurrent *Minecraft Java Edition* players in one persistent world, densely concentrated in a city-sized area (initial standard: 1,000 × 1,000 blocks), maintaining meaningful gameplay and a sustained 20 TPS. This is a target, **not** a demonstrated capability or confirmed record category.

## 1. Mission and compatibility

Create an open-source, reproducibly benchmarked server architecture that improves on unmodified Folia for dense-player simulation. Prioritize **vanilla gameplay semantics** (movement, combat, redstone/block updates, inventories, persistence, tick ordering where relevant) and compatibility with unmodified Java Edition clients. **Plugin compatibility is intentionally minimal**; do not promise Paper/Bukkit plugin compatibility. Deviations from vanilla behavior must be explicit, tested, and documented. No shortcuts such as silently skipping critical game simulation to inflate TPS.

Success is not merely a high connection count: players must perform scripted movement, interaction, building, entity combat, and network traffic in one authoritative world. Maintain separate *dense city* and *distributed world* benchmark scenarios. A densely packed single-chunk crowd is an optional stretch test, not the initial acceptance target.

## 2. Evidence-gated architecture roadmap

0. **Baseline — Folia:** Build an **unmodified, version-pinned** Folia reference implementation; record upstream commit, Minecraft protocol/version, JDK, build flags, hardware and settings. Preserve both a fixed historic baseline and, when practical, periodically check against contemporary upstream Folia.
1. **CPU-only — first priority:** Investigate work partitioning *inside* crowded regions: read-only snapshots, independent entity AI/pathfinding, visibility, broad-phase collision candidates, dependency-aware task scheduling, deterministic conflict resolution and authoritative mutations on an owner thread. Do not assume that arbitrary entity ticking or redstone can safely be parallelized.
   - **Promotion gate:** Repeated controlled dense-region benchmarks show a meaningful, statistically supported improvement over Folia **without violating correctness, p99 latency, stability, memory, or host-resource criteria**.
2. **Hybrid CPU/GPU — separate research branch after CPU gate:** Offload suitably batched, independent calculations (e.g., visibility or collision-candidate searches) to NVIDIA CUDA; benchmark the **entire operation** including data preparation, PCIe transfers, synchronization, and CPU-side validation against the best optimized CPU implementation.
   - **Promotion gate:** Hybrid shows an end-to-end advantage over CPU-only, with justified power/VRAM/resource costs and equivalent correctness.
3. **GPU-resident engine — independent long-term research branch after hybrid evaluation:** Explore GPU-authoritative simulation data in VRAM to reduce repeated host/device transfers. CPU still handles networking, storage, orchestration and unavoidable complex operations. This likely requires a new GPU-friendly engine and may not preserve full vanilla semantics; clearly distinguish research from a drop-in Folia fork.

Failure at a gate **pauses promotion**, not preservation of the branch or research notes. Continue reporting every architecture against **both immediate predecessor and original Folia**. Keep experimental architectures isolated; do not prematurely couple production code to GPU ideas. A shared compute interface may be introduced only where measurement and design justify it.

## 3. Mandatory benchmarking and correctness

**Full-server A/B tests:** Folia vs current experimental build, sequentially on the **same** host (never simultaneously compete for CPU), identical CPU quotas/affinity, JVM/runtime settings, server configuration, cloned starting world, test script, player distribution, hardware and measurement durations. Pin every relevant commit. Alternate or randomize test order; warm the JVM; run at least three repetitions (increase when noise demands). Ensure scripted client actions are logged; account for divergence due to server lag. Separate bot load generation from server cores in controlled tests; an external client generator is preferable at scale.

**Scenario matrix:** idle connections (control), dispersed SMP, dense 1,000 × 1,000 city, progressively smaller crowds, mass PvP, mob pathfinding, collision stress, redstone/block entities, chunk loading and world persistence. Gradually test ~50, 100, 250, 500, 1,000, 2,500, 3,000 and 5,000 *clients*, as infrastructure allows. Headless Mineflayer/protocol clients can simulate players, but their authentication mode and behaviors must be documented; bots are not identical to real users. Direct synthetic engine tests do not substitute for connected-client tests.

**Metrics:** per-region tick time (median/p95/p99/max), sustained TPS/lagging-region share, end-to-end input latency, effective stable player capacity, total CPU and per-core utilization, CPU throttling/pressure, task queueing/synchronization overhead, memory/allocations/GC, networking, client disconnects, disk I/O, correctness errors; GPU stage also VRAM, GPU utilization, transfer time, power draw. Do not equate high total CPU usage with improvement.

**Mandatory microbenchmark suite (JMH):** scheduler dispatch overhead, batch/task granularity crossover, immutable-snapshot cost, shared-state synchronization, contention and throughput at 1/2/3/4/6 workers, pathfinding/AI/collision candidate kernels and memory allocations. Compare sequential, threaded, and later GPU end-to-end variants. JMH results explain *why* something improved; controlled Folia A/B tests decide if the Minecraft server actually improved.

**Correctness:** JUnit tests, targeted Java concurrency tests (e.g. JCStress), deterministic replay/state comparisons where behavior should match, invariant checks, race/deadlock stress testing, persistence/restart validation and adversarial interactions at region boundaries. Minecraft may have inherently nondeterministic inputs; specify the reproducibility and comparison scope. Never accept faster but incorrect simulation.

**Default admission rules (calibrate after baseline):** no correctness failures; sustained 20 TPS at claimed capacity; p99 latency and stability not materially worse; significant target-workload gain beyond benchmark noise (initial hypothesis ≥5%); no unacceptable regressions in unrelated scenarios. A passed microbenchmark alone **never** promotes an architecture.

## 4. Development environment and host protection

**Development host:** user's shared Pop!_OS Linux desktop, Ryzen 5 9600X (6 cores/12 threads), 64 GB RAM, RTX 3090 24 GB VRAM, fast NVMe, ~2.5 GbE. **Mac** used as remote editor over SSH; Codex runs **inside the project directory on Linux**. Do not require a GPU to develop, build or test the CPU track. Check the Folia branch's actual Java/Gradle requirements before installing a JDK; use project Gradle wrapper. Recommended tooling: Git, Python 3, Node.js for Mineflayer, JUnit, JCStress, JMH, Java Flight Recorder, async-profiler/Folia profiler; optional Grafana later.

**Non-negotiable:** This Linux machine runs other self-hosted services. They always take priority. By default, restrict development to approximately **2 logical-CPU equivalents and 6 GiB total project memory**; benchmark mode may temporarily use up to **4 logical-CPU equivalents and 12 GiB** *only when host pressure is low*. These are provisional maximums, not reservations or guaranteed capacity. JVM heap must leave native-memory overhead under the cgroup cap. Do not automatically apply kernel, JVM, Docker, firewall, or system settings globally. Consider `systemd` cgroups v2 CPUQuota/MemoryHigh/MemoryMax, CPU/IO weights and pressure-based admission control. Record host CPU/memory pressure, background activity, thermal state and throttling with each test. Abort/invalidate and retry noisy or host-impacting runs; never degrade critical hosted services. Do not run uncontrolled 1,000–5,000 bot experiments on this workstation. Add remote load generators when justified.

## 5. Security, privacy, licensing and open source

Repository **public from its first published commit**; protect local infrastructure. Review upstream Folia/Paper/Minecraft source and patches, redistribution terms, required notices and naming/trademark considerations **before licensing/publishing derived source**. Do not assume all directories can be relicensed under one chosen license. Until this review, the starter repository intentionally ships **without a source license**; complete license review before opening contributions or publishing derived server code.

Secrets must **never** enter git, issues, PRs, benchmark artifacts, CI logs or example config: no tokens, `.env`, personal paths, SSH keys, IPs, home-host inventories, player IPs, UUID/user lists or production worlds/logs. `.gitignore` is necessary but insufficient. Use placeholder-only `.env.example` and local untracked settings. Add automated secret scanning (e.g. Gitleaks in local hooks and CI), dependency audit, protected main branch, review before merge, minimal CI token permissions, and avoid untrusted PR workflows with secrets. Scan staged content and history **before the first public push**. Rotate/revoke exposed credentials; removing a leaked commit does not make the credential safe. Keep Git author email identity deliberate. All benchmark data intended for publication should be synthetic or sanitized.

## 6. Repository and delivery plan

Use `AGENTS.md` as Codex's operating instructions, this file as the authoritative goals/constraints, and `docs/BENCHMARK_PROTOCOL.md` as the test contract. Keep a clean pinned baseline and experimental fork as reproducible Git worktrees or an equivalent documented upstream/patch workflow; avoid accidental modifications to baseline. Suggested mainline sequence:

- **M0 — Foundation:** Create repo, review licensing, secure defaults, preflight script, pinned toolchains, Codex instructions, source/build policy and CI security checks.
- **M1 — Baseline:** Build unmodified Folia, produce identical world snapshots and a working resource-limited test harness, record repeatability and system noise.
- **M2 — Microbenchmark:** JMH scheduler/concurrency suite and world-state correctness fixtures; no server redesign required yet.
- **M3 — First CPU optimization:** Implement one small safe candidate, e.g. pathfinding or visibility computation; verify invariants and repeat full Folia A/B comparison.
- **M4 — Dense capacity:** Optimize iteratively, gradually ramp scripted clients, publish full methodology, raw aggregate data and regression tests; determine actual CPU capacity rather than assume target reached.
- **M5 — Hybrid:** Separate branch; test justified CUDA candidates against best CPU implementation and Folia.
- **M6 — GPU resident:** Preserve distinct research branch with separate compatibility and scalability evaluation.

## 7. First Codex task

1. Inspect host **read-only** (OS, CPU topology, memory pressure, versions, running service pressure and free storage). Do not upload/share identifying host output.
2. Review these documents and propose a short implementation plan. Do **not** silently execute intensive benchmarks or install packages without approval.
3. Confirm relevant upstream Folia version, Java requirements and licenses. Pin commits only after review.
4. Establish safe build and benchmark scaffolding, automated security checks and a minimal CPU-only scheduler JMH benchmark.
5. Before altering Folia simulation code, capture a valid unmodified Folia baseline and benchmark noise measurements.

**Principle:** correctness first; host safety second; reproducible comparison third; optimizations only when supported by data.
