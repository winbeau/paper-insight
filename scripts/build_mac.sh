#!/usr/bin/env bash
# Build PaperInsight.app and PaperInsight.dmg into ./dist
#   requirements: uv, pnpm, Xcode command line tools (codesign, hdiutil, iconutil)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Frontend"
pnpm -C frontend install --frozen-lockfile
pnpm -C frontend build

echo "==> Backend environment"
uv sync --project backend --group dev

echo "==> App icon"
uv run --project backend python packaging/make_icns.py frontend/public/logo.svg packaging/build/PaperInsight.icns

echo "==> PyInstaller"
rm -rf dist/PaperInsight dist/PaperInsight.app
uv run --project backend pyinstaller --noconfirm --clean \
  --distpath dist --workpath packaging/build/pyinstaller \
  packaging/PaperInsight.spec

echo "==> Ad-hoc code signature"
codesign --force --deep --sign - dist/PaperInsight.app
codesign --verify --deep --strict dist/PaperInsight.app

echo "==> DMG"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
cp -R dist/PaperInsight.app "$STAGING/"
ln -s /Applications "$STAGING/Applications"
rm -f dist/PaperInsight.dmg
hdiutil create -volname PaperInsight -srcfolder "$STAGING" -ov -format UDZO dist/PaperInsight.dmg >/dev/null

echo "Done:"
du -sh dist/PaperInsight.app dist/PaperInsight.dmg
