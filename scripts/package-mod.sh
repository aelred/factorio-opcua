#!/usr/bin/env bash
# Build dist/opc-io_<version>.zip for installing into a Factorio mods/ folder.
set -euo pipefail
cd "$(dirname "$0")/.."
version=$(python3 -c 'import json; print(json.load(open("mod/opc-io/info.json"))["version"])')
name="opc-io_${version}"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p dist
cp -r mod/opc-io "$stage/$name"
rm -f "dist/$name.zip"
(cd "$stage" && python3 -m zipfile -c "$OLDPWD/dist/$name.zip" "$name")
echo "dist/$name.zip"
