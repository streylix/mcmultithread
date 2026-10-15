# Project 5K

[Join the Discord](https://discord.gg/eaNRe7HrjC)

Research toward dense Minecraft Java simulation, with vanilla correctness and
controlled comparison against unmodified Folia. The 5,000-player target has not
been demonstrated. See PROJECT_SPEC.md.

Start with `python3 scripts/preflight.py`. This performs read-only checks and
prints a sanitized readiness report; it does not install software or start loads.
Use `bash scripts/limited-run.sh COMMAND ...` for approved development work.
The launcher refuses to run if a user systemd service cannot enforce limits.
All project loads must share that one service's limits; do not launch parallel
instances. Limits can be lowered with `PROJECT5K_CPU_PERCENT` and
`PROJECT5K_MEMORY_GIB`; development defaults/maxima are 200% CPU and 6 GiB.
The benchmark profile defines a 400% / 12 GiB ceiling but remains blocked until
explicit approval and calibrated host-pressure monitoring are in place.
The server harness is not implemented yet.

This starter intentionally has no source license pending component review.
No upstream server code or binary is included. The local Git repository has no
remote yet; the pre-commit hook runs the project-local Gitleaks (see
docs/TOOLCHAIN.md).
