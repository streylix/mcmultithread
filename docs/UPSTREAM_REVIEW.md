# Upstream review — preliminary, 2026-10-15

Candidate: official PaperMC/Folia `ver/26.2.x`, Minecraft 26.2.
The branch's build.gradle.kts explicitly selects Java toolchain and release 25.
Installed Java 11 cannot build this candidate. Branches move: no Folia commit is
pinned yet and no build is reproducible until an immutable lock is recorded.

Sources reviewed:
- https://github.com/PaperMC/Folia
- https://github.com/PaperMC/Folia/blob/ver/26.2.x/build.gradle.kts
- https://github.com/PaperMC/Folia/blob/ver/26.2.x/gradle.properties
- https://github.com/PaperMC/Folia/blob/ver/26.2.x/README.md
- https://github.com/PaperMC/Folia/blob/ver/26.2.x/PATCHES-LICENSE

The README points to PATCHES-LICENSE for API/server patches, subject to exceptions;
that file contains GPL version 3. This does not establish one license for the
entire derived tree. Before publication, inventory Folia, its pinned Paper tree,
Bukkit/CraftBukkit components, per-file exceptions, bundled dependencies and
Minecraft-derived materials; retain notices and establish distribution obligations.
Review applicable Minecraft redistribution and naming terms separately. Do not
publish a server jar, decompiled Minecraft sources or apply a blanket license on
the strength of this preliminary review. No derived sources have been added.
