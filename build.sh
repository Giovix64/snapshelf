#!/bin/sh
# Build the Snapshelf click package.
#   ./build.sh            -> compiles translations and builds dist/snapshelf.giovix64_<version>_all.click
# Needs: gettext (msgfmt) and the `click` tool (available on Ubuntu Touch, or use `clickable build`).
set -e
cd "$(dirname "$0")"
VERSION=$(python3 -c "import json; print(json.load(open('manifest.json'))['version'])")

# translations: po/<lang>.po -> share/locale/<lang>/LC_MESSAGES/snapshelf.giovix64.mo
for po in po/*.po; do
    lang=$(basename "$po" .po)
    mkdir -p "share/locale/$lang/LC_MESSAGES"
    msgfmt -o "share/locale/$lang/LC_MESSAGES/snapshelf.giovix64.mo" "$po"
done

rm -rf build/click && mkdir -p build/click dist
cp -r manifest.json snapshelf.apparmor snapshelf.desktop assets bin qml share build/click/
find build/click -name __pycache__ -prune -exec rm -rf {} +
click build build/click -d dist >/dev/null
echo "dist/snapshelf.giovix64_${VERSION}_all.click"
