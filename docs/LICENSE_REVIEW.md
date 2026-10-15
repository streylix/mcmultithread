# Component license review — 2026-10-15

Not legal advice. Scope: pinned Folia `acf6733d` / Paper `5d4f9bd0` (docs/TOOLCHAIN.md).
Verified by reading the files named below in the local baseline checkout.

## Components

| Component | Source of terms | Terms |
|---|---|---|
| Folia patches (api/server) | `PATCHES-LICENSE` (Folia root) | GPL-3.0, "subject to exceptions" per README |
| Paper | Paper `LICENSE.md`, `licenses/GPL.md`, `licenses/MIT.md` | GPL-3.0 inherited from Bukkit/CraftBukkit via Spigot; contributors listed in `LICENSE.md` additionally release their work under MIT |
| Paper API (Bukkit-derived) | `paper-api/LICENCE.txt` | GPL-3.0 |
| Minecraft server (decompiled, `folia-server/src/minecraft`) | `META-INF/LICENSE` in that tree | Minecraft EULA + Microsoft Services Agreement; proprietary, not redistributable |
| Gradle wrapper | Gradle distribution `LICENSE` | Apache-2.0 |
| Temurin JDK, Gitleaks | vendor | GPLv2+CE / MIT; local tools only, never committed |

The MIT list is per author, not per file. A file touched by any author not on that
list must be treated as GPL-3.0. In practice, treat all Paper/Folia-derived code as GPL-3.0.

## Conclusions

1. **Publishable now:** our own docs, specs and scripts. They contain no upstream code.
2. **Derived patches** (diffs against Paper/Folia sources) are GPL-3.0 derivative works.
   Publish them under GPL-3.0 with the upstream copyright notices and license texts
   kept, and mark the changes as ours (GPL-3.0 §5a).
3. **Never publish:** decompiled/remapped Minecraft source, the Minecraft server jar,
   paperclip/bundler jars that embed Minecraft, or worlds and assets taken from the game.
   Distribute patches only, as Paper/Folia do; users build locally.
4. **Repository license:** GPL-3.0 for the server-patch tree is the compatible
   choice. Standalone tools (harness, JMH, scripts) may take a separate license (e.g.
   MIT) if they don't link to or copy GPL code; keep them in separate directories
   with their own LICENSE files.
5. **Naming:** don't use "Minecraft", "Folia" or "Paper" in the project or artifact
   name in a way that implies endorsement; "for Minecraft" descriptive use only, per
   Mojang's usage guidelines. "mcmultithread" / "Project 5K" are fine.

## Open questions (unverified)

- The "exceptions" Folia's README mentions next to PATCHES-LICENSE: no exception
  list was found in the checkout. Confirm with upstream.
- Mojang usage guidelines on server software names and monetization (current text
  not re-read for this review).
- Licenses of runtime dependencies pulled by the build (Netty, Adventure, etc.) only
  matter if we redistribute binaries, which we don't plan to.

Owner decision 2026-10-15: GPL-3.0 at the repository root; MIT for `bench/` and `scripts/`.
