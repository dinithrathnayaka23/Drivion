# PyInstaller build recipe. Run it through packaging\build.ps1.
#
# One folder, two programs that share everything in _internal:
#   DrivionApp.exe  no console window: normal use and start at login
#   drivion.exe     console: --doctor, --download-models and the other commands
#
# Models, settings, .env and face data are never bundled. Models are downloaded
# per machine, and the rest belongs to the user in %LOCALAPPDATA%\Drivion.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH).parent

analysis = Analysis(
    [str(root / "packaging" / "entry.py")],
    pathex=[str(root / "src")],
    # The Silero voice-activity model ships inside faster-whisper.
    datas=collect_data_files("faster_whisper"),
    binaries=collect_dynamic_libs("ctranslate2"),
    excludes=["IPython", "matplotlib", "pytest", "tkinter", "torch"],
)
pyz = PYZ(analysis.pure)


def program(name, console):
    return EXE(pyz, analysis.scripts, [], exclude_binaries=True, name=name, console=console, upx=False)


coll = COLLECT(
    program("DrivionApp", console=False),
    program("drivion", console=True),
    analysis.binaries,
    analysis.datas,
    name="Drivion",
    upx=False,
)
