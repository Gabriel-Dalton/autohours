# Build output and cache paths must be outside the checkout; see README.
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
mac = sys.platform == "darwin"
# Reproducible artwork from generate_icons.py, shared with the runtime clock.
icon = root / "packaging" / ("autohours.icns" if mac else "autohours.ico")
datas = [(str(root / "src/autohours/starter.toml"), "autohours")]
web = root / "src/autohours/web"
datas += [(str(path), str(Path("autohours/web") / path.relative_to(web).parent))
          for path in web.rglob("*") if path.is_file()]
if sys.platform == "win32":
    datas += collect_data_files("tzdata")
a = Analysis([str(root / "packaging/launcher.py")], pathex=[str(root / "src")],
             binaries=[], datas=datas, hiddenimports=["tzdata"] if sys.platform == "win32" else [], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
options = dict(name="autohours", console=False, debug=False, strip=False, upx=False,
               icon=str(icon), disable_windowed_traceback=True)
if mac:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **options)
    collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="autohours")
    app = BUNDLE(collection, name="autohours.app", icon=str(icon),
                 bundle_identifier="org.autohours.desktop",
                 info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "1.0.0"})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **options)
