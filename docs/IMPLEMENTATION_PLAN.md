# Foundation implementation plan

1. Complete read-only host/toolchain inspection and upstream review.
2. Verify a shared project cgroup (200% CPU, 6 GiB total), then provision an
   approved JDK and verified upstream Gradle wrapper. Keep downloads project-local.
3. Select an exact Folia revision after review; record its Paper revision,
   Minecraft/protocol version, wrapper checksum, JDK vendor/version and artifact hashes.
4. Build an isolated unmodified baseline, then implement cloned synthetic world
   fixtures, telemetry and a sequential repeated baseline/noise harness.
5. Add the CPU-only JMH scheduler suite and correctness fixtures. Only after a
   valid full-server baseline, select one small CPU optimization.

## Inspection, 2026-10-15

CPU topology and installed memory match the specification. Current pressure was
low at inspection; this is not admission for a later workload. Only a Java 11
runtime was found on PATH, with no javac. Gitleaks was not found. The user systemd
manager is inaccessible from this session. Git metadata is a read-only placeholder,
not a working repository. No packages, builds, servers or benchmarks were run.

## Remaining foundation work

Approved systemd launch and development limit properties were subsequently
verified successfully; sandboxed bus access remains restricted. No builds have run.

Done 2026-10-15 (see docs/TOOLCHAIN.md): project-local Temurin 25 and Gitleaks
(checksum-verified), local Git repository with a Gitleaks pre-commit hook, Folia
baseline pinned to an exact commit with a verified Gradle wrapper, first
contained baseline build.

Also done 2026-10-15: license review (docs/LICENSE_REVIEW.md); GitHub secret
scanning, push protection, Dependabot and CI Gitleaks; host pressure monitor
(scripts/pressure-monitor.py, thresholds provisional); JMH scheduler dispatch
benchmark (bench/, compiles, not yet run); harness design (docs/BASELINE_HARNESS.md).

Deferred by owner: resource guardrails (cgroup caps, single workload slot,
benchmark admission) are suspended; `PROJECT5K_CONTAIN=1` re-enables the launcher
limits. Reinstate before any large or unattended load.

Pending: build reproducibility check; world
fixtures and baseline/noise harness implementation (needs Node.js approval);
first JMH run and analysis.
These are pending, not completed security or reproducibility guarantees.
