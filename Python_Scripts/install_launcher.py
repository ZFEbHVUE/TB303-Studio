#!/usr/bin/env python3
"""
install_launcher.py -- a clickable TB-303 Studio icon on the Linux desktop.

Run it ONCE with the Python that runs the studio (your conda env, if you use
one): the icon then starts that same Python, so it finds numpy, numba,
sounddevice and mido without activating anything.

    python Python_Scripts/install_launcher.py              # app menu + desktop
    python Python_Scripts/install_launcher.py --no-desktop # app menu only
    python Python_Scripts/install_launcher.py --script tb303_studio_AkaiProMPKminiPlus.py
    python Python_Scripts/install_launcher.py --remove

It writes ~/.local/share/applications/tb303-studio.desktop (Activities search,
"Add to favourites" for the dock) and a copy on the desktop, marked as trusted
so GNOME lets it launch. Run it again after moving the folder or changing env.
"""

import argparse
import importlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "Python_Scripts" else HERE
ICON = os.path.join(ROOT, "docs", "tb303_icon.png")
APP_ID = "tb303-studio"
WM_CLASS = "tb303-studio"                # the window's WM_CLASS instance: tk.Tk(className=...) in the studio
APPS_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")


def desktop_dir():
    """Find the desktop directory configured by the operating system."""
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        if out and os.path.isdir(out) and os.path.abspath(out) != os.path.expanduser("~"):
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    # Minimal environments may have an XDG configuration but no xdg-user-dir tool.
    home = os.path.expanduser("~")
    config_dir = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    try:
        with open(os.path.join(config_dir, "user-dirs.dirs"), encoding="utf-8") as config:
            for line in config:
                key, sep, raw = line.strip().partition("=")
                if sep and key == "XDG_DESKTOP_DIR":
                    dest = raw.strip().strip('"').replace("$HOME", home)
                    if os.path.isabs(dest) and os.path.isdir(dest):
                        return None if os.path.abspath(dest) == home else dest
    except OSError:
        pass
    fallback = os.path.join(home, "Desktop")
    return fallback if os.path.isdir(fallback) else None


def quote(arg):
    """Quote one argument for the Exec= line of a .desktop file (Desktop Entry
    spec: % doubled, reserved characters inside double quotes, and \\ " ` $
    escaped there -- a backslash twice over, since the string escape applies first)."""
    arg = arg.replace("%", "%%")
    if not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    inner = (arg.replace("\\", "\\\\\\\\").replace('"', '\\\\"')
                .replace("`", "\\\\`").replace("$", "\\\\$"))
    return '"' + inner + '"'


def knows_docs_layout(script):
    """Studio versions older than this layout look for the skin next to
    themselves, so in Python_Scripts/ they need to be given docs/tb303_skin.png."""
    try:
        with open(script, encoding="utf-8", errors="replace") as f:
            return "_find_skin" in f.read()
    except OSError:
        return True


def entry(script):
    args = [sys.executable, script]
    if not knows_docs_layout(script):
        args.append(os.path.join(ROOT, "docs", "tb303_skin.png"))
    exec_line = " ".join(quote(a) for a in args)
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=TB-303 Studio",
        "Comment=Acid bass synthesizer and sequencer",
        f"Exec={exec_line}",
        f"Path={ROOT}",
        f"Icon={ICON}",
        "Terminal=false",
        "Categories=AudioVideo;Audio;Music;",
        "Keywords=303;acid;bass;synth;sequencer;",
        f"StartupWMClass={WM_CLASS}",
        "StartupNotify=true",
        "",
    ])


def check_python():
    """Say which parts of the studio will work with this Python."""
    needed = [("numpy", "required"), ("PIL", "required (Pillow)"), ("tkinter", "required")]
    optional = [("numba", "real-time audio"), ("sounddevice", "real-time audio"),
                ("mido", "MIDI keyboard"), ("rtmidi", "MIDI keyboard (python-rtmidi)")]
    ok = True
    print(f"Python used by the icon: {sys.executable}")
    for mod, why in needed + optional:
        try:
            importlib.import_module(mod)
            print(f"   ok       {mod}")
        except Exception:
            print(f"   MISSING  {mod:12s} {why}")
            ok = ok and (mod, why) not in needed
    if not ok:
        print("\nThis Python cannot run the studio. Run this script from the env "
              "where `python Python_Scripts/tb303_studio.py` works.")
    return ok


def write(path, text, executable):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    mode = 0o755 if executable else 0o644
    os.chmod(path, mode)


def trust(path):
    """GNOME's desktop icons refuse to launch a file that is not marked trusted."""
    try:
        subprocess.run(["gio", "set", path, "metadata::trusted", "true"],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def refresh_menu():
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", APPS_DIR], capture_output=True)


def main():
    ap = argparse.ArgumentParser(description="Create or remove the TB-303 Studio desktop icon")
    ap.add_argument("--script", default="tb303_studio.py",
                    help="the studio script in Python_Scripts/ (default tb303_studio.py)")
    ap.add_argument("--no-desktop", action="store_true", help="app menu only, no desktop icon")
    ap.add_argument("--remove", action="store_true", help="remove the icon(s)")
    args = ap.parse_args()

    menu_file = os.path.join(APPS_DIR, APP_ID + ".desktop")
    desk = desktop_dir()
    desk_file = os.path.join(desk, APP_ID + ".desktop") if desk else None

    if args.remove:
        for p in (menu_file, desk_file):
            if p and os.path.exists(p):
                os.remove(p)
                print(f"removed  {p}")
        refresh_menu()
        return 0

    script = os.path.join(HERE, args.script)
    if not os.path.isfile(script):
        found = sorted(n for n in os.listdir(HERE) if n.startswith("tb303_studio") and n.endswith(".py"))
        print(f"Studio script not found: {script}")
        if found:
            print("Scripts found here: " + ", ".join(found))
            print("Choose one with:  --script NAME")
        return 1
    if not os.path.isfile(ICON):
        print(f"Warning: icon not found ({ICON}); the launcher will show a generic icon.")

    if not check_python():
        return 1
    if not knows_docs_layout(script):
        print(f"\nNote: {args.script} is an older studio version; the icon hands it docs/tb303_skin.png.")

    text = entry(script)
    write(menu_file, text, executable=True)
    print(f"\napp menu  {menu_file}")
    if desk_file and not args.no_desktop:
        write(desk_file, text, executable=True)
        trust(desk_file)
        print(f"desktop   {desk_file}")
    refresh_menu()
    print("\nDone. Search \"TB-303\" in Activities; right-click it there to add it to the dock.")
    if desk_file and not args.no_desktop:
        print("If the desktop icon shows a cross, right-click it -> \"Allow Launching\".")
    print(f"Without a terminal the studio writes its messages to {os.path.join(ROOT, 'tb303_studio.log')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
