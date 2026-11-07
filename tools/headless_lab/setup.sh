#!/usr/bin/env bash
# Prepare a headless NeoForge 1.21.1 + Mekanism 10.7.19.85 lab server.
# Idempotent: re-running skips finished steps. Usage: setup.sh [LAB_DIR]
set -euo pipefail

LAB_DIR="${1:-${YAN_LAB_DIR:-$HOME/mc-lab}}"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NEOFORGE_VERSION="21.1.255"
SERVER="$LAB_DIR/server"
DL="$LAB_DIR/dl"
mkdir -p "$SERVER/mods" "$DL"

# Mekanism suite: Modrinth URL and expected SHA-256. The core jar matches the
# 2026-10-11 javap audit (docs/recon/mekanism/manifest.json).
MODS=(
  "https://cdn.modrinth.com/data/Ce6I4WUE/versions/5KzzycBT/Mekanism-1.21.1-10.7.19.85.jar 004dbc9f3106f4d192aeaa1ee1190dd16ec9ca8059ed3d093b80034f4c574f43"
  "https://cdn.modrinth.com/data/OFVYKsAk/versions/a6gl7srE/MekanismGenerators-1.21.1-10.7.19.85.jar 0e5783b111e756f27b48c62b2f0e02fff750c77f7985ff809bfadc5f444ba4ac"
  "https://cdn.modrinth.com/data/tqQpq1lt/versions/v5zlSE9s/MekanismTools-1.21.1-10.7.19.85.jar e1dbca7d70df150101da535f6ab4b165a2e402fde830d34df75b58d9aad24dd8"
  "https://cdn.modrinth.com/data/a6F3uASn/versions/6mkdykZa/MekanismAdditions-1.21.1-10.7.19.85.jar 3d8a6ed67f5ccf3797ad9d5236ec4e22b74481aa9cd45636feb16f89e1d56311"
)
for entry in "${MODS[@]}"; do
  url="${entry% *}"; sha="${entry#* }"; jar="$SERVER/mods/$(basename "$url")"
  if [ ! -f "$jar" ] || ! echo "$sha  $jar" | sha256sum -c --quiet - 2>/dev/null; then
    curl -sSLo "$jar" "$url"
    echo "$sha  $jar" | sha256sum -c --quiet -
  fi
done

if [ ! -f "$SERVER/run.sh" ]; then
  curl -sSLo "$DL/neoforge-installer.jar" \
    "https://maven.neoforged.net/releases/net/neoforged/neoforge/$NEOFORGE_VERSION/neoforge-$NEOFORGE_VERSION-installer.jar"
  (cd "$SERVER" && java -jar "$DL/neoforge-installer.jar" --installServer . > "$LAB_DIR/install.log" 2>&1)
fi

# Running a Minecraft server requires accepting the Minecraft EULA
# (https://aka.ms/MinecraftEULA). The repository owner accepted it for this lab.
echo "eula=true" > "$SERVER/eula.txt"
cp "$(dirname "$0")/server.properties" "$SERVER/server.properties"
echo "-Xmx6G" > "$SERVER/user_jvm_args.txt"

(cd "$REPO_DIR/mod" && bash ./gradlew build --no-daemon -q)
cp "$REPO_DIR/mod/build/libs/mcbuild_live-1.0.0.jar" "$SERVER/mods/"
echo "headless lab ready in $LAB_DIR"
