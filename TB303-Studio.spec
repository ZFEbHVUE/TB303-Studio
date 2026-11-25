# -*- mode: python -*-
# PyInstaller spec of the stand-alone TB-303 Studio: one folder, no console window.
#
#   pip install pyinstaller numpy scipy numba pygame sounddevice soundfile pillow mido python-rtmidi
#   pyinstaller --noconfirm TB303-Studio.spec
#   dist/TB303-Studio/TB303-Studio --self-test
#
# dist/TB303-Studio/ then holds the program, _internal/ (Python and the
# libraries) and, copied by the end of this file, the folders the studio reads
# next to it: doc/skin, docs (default skin and icon), Instruments, Projects.
# .github/workflows/executables.yml runs this on Linux and Windows.
import os
import shutil
import sys

from PyInstaller.utils.hooks import collect_submodules

NAME = "TB303-Studio"
HERE = os.path.abspath(SPECPATH)                       # noqa: F821 (set by PyInstaller)

binaries = []
if sys.platform.startswith("linux"):
    # PortAudio for machines without libportaudio2; standalone_main.py uses the
    # system's copy first. PORTAUDIO_LIB can point to it, else the usual places.
    candidates = [os.environ.get("PORTAUDIO_LIB", "")] + [
        os.path.join(d, "libportaudio.so.2")
        for d in ("/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib64", "/usr/lib")]
    found = next((p for p in candidates if p and os.path.isfile(p)), None)
    if found is None:
        print("WARNING: libportaudio.so.2 not found: the executable will need the system's PortAudio")
    else:
        binaries.append((found, "."))

a = Analysis(                                          # noqa: F821
    [os.path.join(HERE, "Python_Scripts", "standalone_main.py")],
    pathex=[os.path.join(HERE, "Python_Scripts")],
    binaries=binaries,
    datas=[],
    # Imports the analysis cannot see: mido loads its MIDI backend by name, and
    # Pillow's Tk extension (PIL._imagingtk) imports PIL._tkinter_finder from C.
    hiddenimports=collect_submodules("mido.backends") + ["rtmidi", "PIL._tkinter_finder"],
    excludes=["IPython", "matplotlib", "pandas", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)                                      # noqa: F821
exe = EXE(                                             # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,                                     # Windows: no terminal window
    icon=os.path.join(HERE, "docs", "tb303_icon.png"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)  # noqa: F821

# --- the studio's folders, next to the program ------------------------------
dist = os.path.join(DISTPATH, NAME)                    # noqa: F821


def copy(src, dst=None, ignore=None):
    src_path = os.path.join(HERE, src)
    dst_path = os.path.join(dist, dst or src)
    if os.path.isdir(src_path):
        shutil.copytree(src_path, dst_path, ignore=ignore, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)


copy("doc/skin", ignore=shutil.ignore_patterns("Inlay_Sources"))   # skins, Mk III inlays, photo
for name in ("tb303_skin.png", "tb303_icon.png"):                    # default skin and icon
    copy(os.path.join("docs", name))
copy("Instruments")
copy("Projects")
for name in ("README.md", "CLASSIC-GUIDE.md", "ROLAND-PANEL.md", "LICENSE"):
    copy(name)
