"""Regression tests for the English interface and legacy factory sample names."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Python_Scripts"))
import studio_file_dialog as chooser
import studio_messages as messages
import tb303_studio as studio


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


class EnglishInterfaceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(self.root.destroy)
        self.root.tk.call("package", "require", "msgcat")
        self.root.tk.call("::msgcat::mclocale", "fr")
        self.root.update()

    def test_english_menu_opens_track_and_pitch_editors(self):
        with patch.object(studio, "_HAS_RT", False), patch.object(studio, "_HAS_PYGAME", False):
            app = studio.SkinStudio(self.root, studio._find_skin())
        self.addCleanup(app.close)
        self.assertEqual(self.root.tk.call("::msgcat::mclocale"), "en")
        bar = self.root.nametowidget(self.root.cget("menu"))
        menu = self.root.nametowidget(bar.entrycget("Sequencer", "menu"))
        self.assertEqual(menu.entrycget("BACK - Undo", "accelerator"), "Ctrl+Z")
        self.assertEqual(menu.entrycget("REDO - Redo", "accelerator"), "Ctrl+Y")
        self.assertEqual(menu.entrycget("Cancel queued pattern", "accelerator"), "Esc")
        clock = self.root.nametowidget(menu.entrycget("MIDI Clock (24 PPQN)", "menu"))
        self.assertEqual([clock.entrycget(i, "label") for i in range(3)],
                         ["Arm current pattern", "Arm selected track", "Use internal clock"])
        menu.invoke("Track Write / Play")
        self.root.update()
        panel = app._classic_win
        self.assertEqual(panel.title(), "TB-303 Studio · Classic Sequencer")
        self.assertEqual(panel.book.index("current"), 1)
        menu.invoke("Classic: Pitch / Time")
        self.root.update()
        self.assertEqual(panel.book.index("current"), 0)
        texts = {str(w.cget("text")) for w in walk(panel.p) if isinstance(w, (ttk.Button, ttk.Label))}
        self.assertTrue({"INS Step", "DEL Step", "Tie", "Rest", "Length"} <= texts)
        self.assertTrue(app._face.texts[0].startswith("1A-1  STEP"))

    def test_nested_confirmations_keep_english_choices_and_restore_grab(self):
        owner = tk.Toplevel(self.root)
        owner.update()
        owner.grab_set()
        def answer(fn, action):
            observed = []
            def pick():
                dialogs = [w for w in owner.winfo_children() if isinstance(w, messages._Message)]
                if not dialogs:
                    owner.after(10, pick)
                    return
                dialog = dialogs[0]
                buttons = {str(w.cget("text")): w for w in walk(dialog) if isinstance(w, ttk.Button)}
                observed.extend(buttons)
                if action == "Escape":
                    dialog.focus_force()
                    dialog.update()
                    dialog.event_generate("<Escape>")
                elif action == "Close":
                    dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))
                else:
                    buttons[action].invoke()
            owner.after(35, pick)
            result = fn("Test", "Keep this take?", parent=owner)
            self.assertIs(owner.grab_current(), owner)
            return result, observed
        for action, expected in (("Yes", True), ("No", False), ("Escape", None), ("Close", None)):
            with self.subTest(action=action):
                value, labels = answer(messages.askyesnocancel, action)
                self.assertIs(value, expected)
                self.assertEqual(labels, ["Yes", "No", "Cancel"])
        self.assertEqual(answer(messages.askyesno, "Close"), (False, ["Yes", "No"]))
        self.assertEqual(answer(messages.showerror, "OK"), ("ok", ["OK"]))

    def test_file_picker_uses_english_controls_and_returns_original_filename(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(chooser, "_PREFS", {}), \
             patch.object(chooser, "_save_preferences"), patch.object(chooser, "_SHORTCUTS", lambda: []):
            target = Path(temp) / "My take.wav"
            target.touch()
            seen = {}
            def select():
                dialog = chooser._ACTIVE
                if not dialog or dialog._loading:
                    self.root.after(10, select)
                    return
                seen["labels"] = {str(w.cget("text")) for w in walk(dialog)
                                  if isinstance(w, (ttk.Button, ttk.Checkbutton, ttk.Label))}
                seen["columns"] = [dialog.tree.heading(c, "text").strip(" ▲▼")
                                   for c in ("#0", "kind", "size", "modified")]
                seen["title"] = dialog.title()
                dialog.name_var.set(target.name)
                dialog.accept()
            self.root.after(30, select)
            result = chooser.askopenfilename(parent=self.root, initialdir=temp, filetypes=[("Audio", "*.wav")])
            self.assertEqual(result, str(target))
            self.assertEqual(seen["title"], "Open file")
            self.assertEqual(seen["columns"], ["Name", "Type", "Size", "Modified"])
            self.assertTrue({"Search:", "Show hidden files", "New folder", "Open", "Cancel",
                             "Back", "Forward", "Add to favorites"} <= seen["labels"])
            self.assertIsNone(self.root.grab_current())
            self.assertTrue(self.root.winfo_viewable())


class FactorySampleTests(unittest.TestCase):
    def test_older_filename_resolves_without_overriding_a_users_file(self):
        aliases = json.loads((ROOT / "Instruments" / "factory_sample_aliases.json").read_text())
        app = object.__new__(studio.SkinStudio)
        app.samples = {}
        with tempfile.TemporaryDirectory() as td, patch.object(app, "_register_sample", side_effect=lambda path, *a, **k: Path(path)):
            folder = Path(td)
            project = folder / "old.tb303"
            local_samples = folder / "Instruments"
            local_samples.mkdir()
            for original, current in aliases.items():
                warnings = []
                desc = {"kind": "sample", "file": original}
                factory = app._resolve_instr(desc, str(project), warnings)
                self.assertEqual(factory, ROOT / "Instruments" / current)
                self.assertTrue(factory.is_file())
                local = local_samples / original
                local.touch()
                with patch.object(app, "_copy_into_instruments", side_effect=lambda p: p):
                    self.assertEqual(app._resolve_instr(desc, str(project), warnings), local)
                self.assertEqual(warnings, [])
                self.assertIn(current, app._library_files())
                self.assertNotIn(original, app._library_files())

