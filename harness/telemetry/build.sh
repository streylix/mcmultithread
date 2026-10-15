#!/usr/bin/env bash
# Compile TickTelemetry against a server directory that paperclip has already unpacked.
# Usage: bash harness/telemetry/build.sh SERVER_DIR  -> harness/telemetry/build/TickTelemetry.jar
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
server=$(cd "$1" && pwd)
root=$(cd "$here/../.." && pwd)
javac=${JAVAC:-$root/.local/jdk-25/bin/javac}
jar=${JAR:-$root/.local/jdk-25/bin/jar}
cp=$(find "$server/libraries" "$server/versions" -name '*.jar' | paste -sd:)
rm -rf "$here/build" && mkdir -p "$here/build/classes"
"$javac" --release 25 -proc:none -d "$here/build/classes" -cp "$cp" $(find "$here/src" -name '*.java')
cp "$here/src/plugin.yml" "$here/build/classes/"
"$jar" --create --file "$here/build/TickTelemetry.jar" -C "$here/build/classes" .
echo "$here/build/TickTelemetry.jar"
