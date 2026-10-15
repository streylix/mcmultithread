# Toolchain and baseline lock

All tools are project-local under `.local/` (ignored). Nothing is installed
system-wide. Re-verify checksums when re-provisioning.

## JDK

- Eclipse Temurin `jdk-25.0.4.1+1`, linux x64 hotspot
- Archive: `OpenJDK25U-jdk_x64_linux_hotspot_25.0.4.1_1.tar.gz`
- SHA-256 (from Adoptium API, verified): `dbb698396d478e7fa2b1e50f4103324b2a99b90569ee27c33f2261f9215cf41e`
- Location: `.local/jdk-25`

## Gitleaks

- `v8.30.1`, `gitleaks_8.30.1_linux_x64.tar.gz`, verified against the release
  `gitleaks_8.30.1_checksums.txt`
- Location: `.local/bin/gitleaks`; used by `.git/hooks/pre-commit` (staged scan).
- Full-tree scans report one generic-api-key false positive in
  `.local/jdk-25/conf/security/java.security`; `.local/` is not tracked.

## Folia baseline (unmodified)

- Repository: https://github.com/PaperMC/Folia, branch `ver/26.2.x`
- Commit: `acf6733ddebcb4b1cd07360d11370c530b8125a2` (2026-09-22)
- Paper ref (`gradle.properties`): `5d4f9bd0e4f6b1ef70d07feb411580cef7d1a746`
- Minecraft `26.2`, channel BETA
- Checkout: `upstream/folia-baseline` (ignored; do not edit)

## Folia 26.1 baseline (harness target)

Mineflayer 4.39.0 / minecraft-data 3.117.0 have no 26.2 protocol data, so
connected-client tests use the 26.1 line. The 26.2 checkout above is kept.

- Branch `ver/26.1.x`, commit `62dc0f257a4f5de1ef2eae8cf1627156a769c67f` (2026-05-06)
- Paper ref `b4682bfef616ac62e73cc96046dacdf4a6f53eeb`, Minecraft `26.1.2`
  (Mineflayer maps it to 26.1 data, protocol 775)
- Same JDK and verified Gradle 9.4.1 wrapper; checkout `upstream/folia-26.1-baseline`
- Built 2026-10-15, source unmodified:
  - `folia-paperclip-26.1.2.local-SNAPSHOT.jar` `8057a60e002ae33ff24a95101d509a3ef597acd38511ae87e5df9353faea03ef`
  - `folia-bundler-26.1.2.local-SNAPSHOT.jar` `6212cae7b116c1159e1c6fe3b91aa9126c48ee82b225b9764b8e6a6c4a00f621`
  - `folia-server-26.1.2.local-SNAPSHOT.jar` `45b8dbafabf2cd62f89c7271fd1d2e46b62fdbf86f361f15c6b47f1063b2d000`
- Smoke test 2026-10-15: 5 Mineflayer bots spawned, moved and chatted
  (`harness/bots/smoke.js`).

## Node.js

- v24.22.0 LTS linux-x64, verified against nodejs.org `SHASUMS256.txt`; `.local/node`
- Bot dependencies locked in `harness/bots/package-lock.json`

## Gradle

- Wrapper from the Folia checkout, distribution `gradle-9.4.1-bin.zip`
- `gradle-wrapper.jar` SHA-256 `55243ef57851f12b070ad14f7f5bb8302daceeebc5bce5ece5fa6edb23e1145c`
  matches the official Gradle 9.4.1 wrapper checksum.
- Distribution SHA-256 (official): `2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb`;
  verify the downloaded zip under `.local/gradle-home/wrapper/dists` after first use.
- `GRADLE_USER_HOME=.local/gradle-home`, `--no-daemon`, `--max-workers=2`.

## Test plugins (local only, never committed)

- Chunky 1.5.3 (Modrinth `MdY6JATr`, `folia-supported: true`, MC 26.1.2–26.3),
  sha512 verified against Modrinth; SHA-256 `530d2c7430a96a39957391b7088be144daa3108f7665896d1c23aa8dd4af32f3`.
  Location: `.local/plugins/`. Used only to pregenerate fixture worlds, never during
  measured runs.

## Build artifacts

First baseline build 2026-10-15: `applyAllPatches` then
`folia-server:createPaperclipJar`, Temurin 25.0.4.1, no source changes
(`git status` clean). Outputs in `upstream/folia-baseline/folia-server/build/libs/`:

- `folia-paperclip-26.2.local-SNAPSHOT.jar` `8b80c258274219a8a3bfb7e36605ce0932a7ea4be822de450d735a9478ec1eff`
- `folia-bundler-26.2.local-SNAPSHOT.jar` `05b76b9f58f8f06e9427d15216732d7380fe6477d6f25850ca62119af170159a`
- `folia-server-26.2.local-SNAPSHOT.jar` `48b431424b52c200b98c1f50168cdb181091feaef8b940001e57d6f19725126b`

Local builds are not yet verified bit-reproducible; rebuild and compare before relying
on these hashes as an identity check. Never publish these jars (docs/LICENSE_REVIEW.md).
