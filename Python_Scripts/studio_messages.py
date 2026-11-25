"""Studio message dialogs with English buttons, independent of the desktop language."""
from contextlib import contextmanager
import tkinter as tk
from tkinter import simpledialog, ttk


def use_english(widget):
    """Select English for Tk's own widget strings without changing the process locale."""
    try:
        widget.tk.call("package", "require", "msgcat")
        widget.tk.call("::msgcat::mclocale", "en")
    except tk.TclError:
        pass  # Studio labels are explicit even on a minimal Tk installation.


class _Message(simpledialog.Dialog):
    def __init__(self, parent, title, text, choices, dismissed, default, icon):
        self.icon = icon
        self.text, self.choices = str(text), choices
        self.dismissed, self.default = dismissed, default
        super().__init__(parent, title)

    def body(self, master):
        tk.Label(master, bitmap=self.icon).pack(side="left", padx=(12, 4), pady=10)
        ttk.Label(master, text=self.text, justify="left", wraplength=520,
                  padding=(10, 12)).pack(side="left", fill="both", expand=True)

    def buttonbox(self):
        row = ttk.Frame(self, padding=(10, 0, 10, 10))
        row.pack()
        for caption, value in self.choices:
            button = ttk.Button(row, text=caption, command=lambda v=value: self._choose(v))
            button.pack(side="left", padx=4)
            if caption == self.default:
                self.initial_focus = button
        self.bind("<Return>", self._enter)
        self.bind("<Escape>", self.cancel)

    def _enter(self, event):
        button = self.focus_get()
        (button if isinstance(button, ttk.Button) and button.winfo_toplevel() is self
         else self.initial_focus).invoke()
        return "break"

    def _choose(self, value):
        self.result = value
        super().cancel()

    def cancel(self, event=None):
        self._choose(self.dismissed)
        return "break"


@contextmanager
def _modal_owner(parent):
    owner = parent if parent is not None else tk._default_root
    if owner is not None:
        owner = owner.winfo_toplevel()
    previous = owner.grab_current() if owner is not None else None
    mode = previous.grab_status() if previous is not None else None
    focus = owner.focus_get() if owner is not None else None
    try:
        yield owner
    finally:
        # Restore the enclosing file chooser's modality and the focused control.
        try:
            if previous is not None and previous.winfo_exists():
                if mode == "global":
                    previous.grab_set_global()
                else:
                    previous.grab_set()
            if focus is not None and focus.winfo_exists():
                focus.focus_set()
        except tk.TclError:
            pass


def _show(title, message, parent, choices, dismissed, default, icon="question"):
    with _modal_owner(parent) as owner:
        return _Message(owner, title, message, choices, dismissed, default, icon).result


def askstring(title, prompt, *, parent=None):
    with _modal_owner(parent) as owner:
        return simpledialog.askstring(title, prompt, parent=owner)


def showinfo(title, message, *, parent=None):
    return _show(title, message, parent, (("OK", "ok"),), "ok", "OK", "info")


def showwarning(title, message, *, parent=None):
    return _show(title, message, parent, (("OK", "ok"),), "ok", "OK", "warning")


def showerror(title, message, *, parent=None):
    return _show(title, message, parent, (("OK", "ok"),), "ok", "OK", "error")


def askyesno(title, message, *, parent=None):
    return _show(title, message, parent, (("Yes", True), ("No", False)), False, "No")


def askyesnocancel(title, message, *, parent=None):
    return _show(title, message, parent, (("Yes", True), ("No", False), ("Cancel", None)),
                 None, "Cancel")

