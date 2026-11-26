# -*- mode: python -*-
# PyInstaller spec of the stand-alone TB-303 Studio: one folder, no console window.
#
#   pip install pyinstaller numpy scipy numba pygame sounddevice soundfile pillow mido python-rtmidi
#   pyinstaller --noconfirm TB303-Studio.spec
#   dist/TB303-Studio/TB303-Studio --self-test
#
# dist/TB303-Studio/ then holds the program, _internal/ (Python and the
# libraries) and, copied by the end of this file, the folders the studio reads
# next to it: doc/skin, docs (default skin and icon), Instruments, Projects, and
# licenses/ (the licenses of the libraries inside).
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
    icon=os.path.join(HERE, "docs", "tb303_icon.ico"),  # used by Windows only
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


# --- licenses of what the program contains (licenses/) ----------------------
def collect_licenses():
    import importlib.metadata
    import re
    import tkinter

    root = os.path.join(dist, "licenses")
    os.makedirs(root, exist_ok=True)
    is_license = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE)[^/]*$", re.I)
    lines = ["Licenses of the software inside TB-303 Studio's executable.",
             "TB-303 Studio itself: MIT License (../LICENSE).", ""]

    def take(src, *dst):
        if src and os.path.isfile(src):
            target = os.path.join(root, *dst)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(src, target)
            return True
        return False

    def license_name(meta):
        if meta.get("License-Expression"):
            return meta["License-Expression"]
        classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or ()
                       if c.startswith("License ::")]
        if classifiers:
            return ", ".join(classifiers)
        text = (meta.get("License") or "").strip().splitlines()
        return text[0][:60] if text else "see the license files"

    for name in ("numpy", "scipy", "numba", "llvmlite", "pygame", "sounddevice", "soundfile",
                 "pillow", "mido", "python-rtmidi", "packaging", "pyinstaller"):
        try:
            dist_info = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        found = [f for f in dist_info.files or () if is_license.search(str(f))]
        for f in found:
            take(str(dist_info.locate_file(f)), name, *str(f).split("/"))
        kind = license_name(dist_info.metadata)
        if name == "pyinstaller":     # only its loader is inside, under the exception of COPYING.txt
            kind = "GPL 2 with an exception: the programs it builds may use any license"
        lines.append(f"{name} {dist_info.version}: {kind}"
                     + ("" if found else " (no license file in the package)"))
    # pygame ships no license file: it is under the GNU LGPL 2.1
    take(os.path.join(HERE, "licenses", "LGPL-2.1.txt"), "pygame", "LGPL-2.1.txt")
    lines.append("pygame (with SDL, SDL_mixer): GNU LGPL 2.1, pygame/LGPL-2.1.txt; "
                 "source at https://github.com/pygame/pygame")
    lines.append("libsndfile (inside soundfile): GNU LGPL 2.1 or later, soundfile/_soundfile_data/COPYING")
    # Python and Tcl/Tk
    for candidate in (os.path.join(sys.base_prefix, "LICENSE.txt"),
                      os.path.join(sys.base_prefix, "lib", f"python{sys.version_info[0]}.{sys.version_info[1]}",
                                   "LICENSE.txt")):
        if take(candidate, "python", "LICENSE.txt"):
            lines.append(f"Python {sys.version.split()[0]}: PSF License, python/LICENSE.txt")
            break
    try:
        tcl_dir = tkinter.Tcl().eval("info library")
    except Exception:
        tcl_dir = ""
    tcl_found = [take(src, "tcl-tk", dst) for src, dst in (
        (os.path.join(tcl_dir, "license.terms"), "license.terms"),                 # Windows Python
        (os.path.join(os.path.dirname(tcl_dir), "license.terms"), "license.terms"),
        ("/usr/share/doc/libtcl8.6/copyright", "tcl-copyright"),                   # Debian, Ubuntu
        ("/usr/share/doc/libtk8.6/copyright", "tk-copyright"))]
    if any(tcl_found):
        lines.append("Tcl/Tk: BSD-style license, tcl-tk/")
    if sys.platform.startswith("linux"):
        if take("/usr/share/doc/libportaudio2/copyright", "portaudio", "copyright"):
            lines.append("PortAudio: MIT License, portaudio/copyright")
    with open(os.path.join(root, "README.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


collect_licenses()
