# Project operating instructions

Read PROJECT_SPEC.md before work; it is the authoritative project scope.
Use docs/BENCHMARK_PROTOCOL.md for measurement acceptance.

- Correctness first, host safety second, reproducible comparisons third.
- Default aggregate project limit: 200% CPU and 6 GiB memory, including child processes.
- Do not install packages or run intensive benchmarks without explicit approval.
- Never run builds or load generators without verified resource containment.
- No global system changes. Other hosted services take priority.
- Keep the unmodified Folia baseline isolated; record exact revisions before building.
- No simulation changes until a valid baseline and noise measurements exist.
- Keep host inventories, identifiers, credentials, worlds and raw logs local and ignored.
- No publication of derived code until the component license review is complete.
- Use the selected upstream's Gradle wrapper; do not invent wrapper binaries or use a global Gradle.
- Do not claim progress gates passed from microbenchmarks alone.
