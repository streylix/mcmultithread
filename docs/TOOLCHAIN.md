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

## Gradle

- Wrapper from the Folia checkout, distribution `gradle-9.4.1-bin.zip`
- `gradle-wrapper.jar` SHA-256 `55243ef57851f12b070ad14f7f5bb8302daceeebc5bce5ece5fa6edb23e1145c`
  matches the official Gradle 9.4.1 wrapper checksum.
- Distribution SHA-256 (official): `2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb`;
  verify the downloaded zip under `.local/gradle-home/wrapper/dists` after first use.
- `GRADLE_USER_HOME=.local/gradle-home`, `--no-daemon`, `--max-workers=2`.

## Build artifacts

First baseline build 2026-10-15: `applyAllPatches` then
`folia-server:createPaperclipJar`, Temurin 25.0.4.1, no source changes
(`git status` clean). Outputs in `upstream/folia-baseline/folia-server/build/libs/`:

- `folia-paperclip-26.2.local-SNAPSHOT.jar` `8b80c258274219a8a3bfb7e36605ce0932a7ea4be822de450d735a9478ec1eff`
- `folia-bundler-26.2.local-SNAPSHOT.jar` `05b76b9f58f8f06e9427d15216732d7380fe6477d6f25850ca62119af170159a`
- `folia-server-26.2.local-SNAPSHOT.jar` `48b431424b52c200b98c1f50168cdb181091feaef8b940001e57d6f19725126b`

Local builds are not yet verified bit-reproducible; rebuild and compare before relying
on these hashes as an identity check. Never publish these jars (docs/LICENSE_REVIEW.md).
