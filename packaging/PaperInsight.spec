# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for PaperInsight.app (onedir bundle, arm64).
# Build with scripts/build_mac.sh, which first builds frontend/dist and the icon.

import os
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"
ICON = ROOT / "packaging" / "build" / "PaperInsight.icns"
VERSION = "0.3.2"

if not (DIST / "index.html").exists():
    raise SystemExit("frontend/dist is missing: run `pnpm -C frontend build` first")

datas = [(str(DIST), "frontend_dist")]
binaries = []
hiddenimports = (
    collect_submodules("app")
    + collect_submodules("uvicorn")
    + collect_submodules("apscheduler")
)
for package in ("webview",):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden
datas += copy_metadata("apscheduler")

# uv is shipped so the app can install the local MinerU runtime on demand
uv = os.environ.get("PAPER_INSIGHT_UV") or shutil.which("uv")
if not uv:
    raise SystemExit("uv not found: install it (brew install uv) or set PAPER_INSIGHT_UV")
binaries.append((os.path.realpath(uv), "bin"))

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "respx", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PaperInsight",
    console=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(exe, a.binaries, a.datas, name="PaperInsight")

app = BUNDLE(
    coll,
    name="PaperInsight.app",
    icon=str(ICON) if ICON.exists() else None,
    bundle_identifier="dev.winbeau.paperinsight",
    version=VERSION,
    info_plist={
        "CFBundleName": "PaperInsight",
        "CFBundleDisplayName": "PaperInsight",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.education",
        # The UI is served from http://127.0.0.1:<port>
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
