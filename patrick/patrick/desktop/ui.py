"""Fenêtres natives du lanceur (tkinter) : écran de démarrage, assistant de premier démarrage, choix de dossier.

La logique du lanceur ne parle qu'à un `Reporter` : ici l'implémentation graphique (`TkReporter`), ailleurs
(`--no-ui`, tests) une implémentation console ou factice.
"""
from __future__ import annotations

import contextlib
import os
import queue
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from patrick.desktop import share


class Reporter:
    """Interface minimale entre le lanceur et l'utilisateur. Ne fait rien par défaut."""

    def status(self, text: str) -> None: ...
    def hide(self) -> None: ...
    def error(self, text: str) -> None: ...
    def info(self, text: str) -> None: ...

    def ask_setup(self) -> dict | None:
        """Assistant de premier démarrage. Renvoie `{"folder": str | None, "wealth_reference": bool,
        "schedule": bool}` ou `None` (« Plus tard »)."""
        return None


class ConsoleReporter(Reporter):
    def status(self, text: str) -> None:
        print(text, flush=True)

    def error(self, text: str) -> None:
        print(f"ERREUR : {text}", file=sys.stderr, flush=True)

    def info(self, text: str) -> None:
        print(text, flush=True)


def notify(text: str, *, error: bool = False) -> None:
    """Boîte de message autonome (processus sans console, p. ex. `pythonw`). Ne lève jamais."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            (messagebox.showerror if error else messagebox.showinfo)("PATRICK", text, parent=root)
        finally:
            root.destroy()
    except Exception:  # noqa: BLE001 -- pas de fenêtre possible : le journal reste la trace
        print(text, file=sys.stderr)


def pick_folder(initial: str | None = None, title: str = "Choisis le dossier partagé") -> str | None:
    """Sélecteur de dossier natif (bloquant). Renvoie le chemin choisi, ou None si annulé."""
    import tkinter as tk
    from tkinter import filedialog

    _enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        start = initial if initial and os.path.isdir(initial) else str(Path.home())
        chosen = filedialog.askdirectory(parent=root, initialdir=start, title=title, mustexist=False)
    finally:
        root.destroy()
    return os.path.normpath(chosen) if chosen else None


def _enable_dpi_awareness() -> None:
    if os.name == "nt":
        with contextlib.suppress(Exception):
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)


def _icon_path() -> Path | None:
    icon = Path(__file__).resolve().parents[3] / "app" / "patrick.ico"
    return icon if icon.exists() else None


class TkReporter(Reporter):
    """Écran de démarrage + assistant. Tk vit dans le fil principal : le lanceur s'exécute dans un autre fil
    (`run`) et poste ses messages dans une file que le fil principal vide toutes les 100 ms."""

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        _enable_dpi_awareness()
        self._tk, self._ttk = tk, ttk
        self.root = tk.Tk()
        self.root.withdraw()
        self._queue: queue.Queue = queue.Queue()
        self._splash = None
        self._label = None
        self._code = 0
        icon = _icon_path()
        if icon:
            with contextlib.suppress(Exception):
                self.root.iconbitmap(default=str(icon))

    # --- appelés depuis le fil du lanceur -----------------------------------------------------------------------
    def status(self, text: str) -> None:
        self._queue.put(("status", text))

    def hide(self) -> None:
        self._queue.put(("hide", None))

    def error(self, text: str) -> None:
        self._call(lambda: self._messagebox("showerror", text))

    def info(self, text: str) -> None:
        self._call(lambda: self._messagebox("showinfo", text))

    def ask_setup(self) -> dict | None:
        return self._call(self._wizard)

    def _call(self, fn: Callable[[], object]) -> object:
        """Exécute `fn` dans le fil Tk et attend son résultat."""
        done, box = threading.Event(), {}
        self._queue.put(("call", (fn, done, box)))
        done.wait()
        if "error" in box:
            raise box["error"]
        return box.get("value")

    # --- fil principal -----------------------------------------------------------------------------------------
    def run(self, target: Callable[[Reporter], int]) -> int:
        def worker() -> None:
            try:
                self._code = target(self)
            except BaseException as exc:  # noqa: BLE001 -- dernier filet : afficher l'erreur plutôt que mourir en silence
                self._code = 1
                self.error(f"Erreur inattendue : {exc}")
            finally:
                self._queue.put(("quit", None))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll)
        self.root.mainloop()
        with contextlib.suppress(Exception):
            self.root.destroy()
        return self._code

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "status":
                    self._show_splash(payload)
                elif kind == "hide":
                    self._close_splash()
                elif kind == "call":
                    fn, done, box = payload
                    try:
                        box["value"] = fn()
                    except BaseException as exc:  # noqa: BLE001 -- transmis au fil appelant
                        box["error"] = exc
                    finally:
                        done.set()
                elif kind == "quit":
                    self._close_splash()
                    self.root.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _show_splash(self, text: str) -> None:
        tk, ttk = self._tk, self._ttk
        if self._splash is None:
            win = tk.Toplevel(self.root)
            win.title("PATRICK")
            win.resizable(False, False)
            win.attributes("-topmost", True)
            win.protocol("WM_DELETE_WINDOW", lambda: None)
            frame = ttk.Frame(win, padding=(24, 18))
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text="PATRICK", font=("Segoe UI", 15, "bold")).pack(anchor="w")
            self._label = ttk.Label(frame, text=text, font=("Segoe UI", 10), wraplength=380, justify="left")
            self._label.pack(anchor="w", pady=(6, 12), fill="x")
            bar = ttk.Progressbar(frame, mode="indeterminate", length=380)
            bar.pack(fill="x")
            bar.start(12)
            self._center(win, 430, 150)
            self._splash = win
        self._label.configure(text=text)

    def _close_splash(self) -> None:
        if self._splash is not None:
            self._splash.destroy()
            self._splash = None

    def _center(self, win, width: int, height: int) -> None:
        win.update_idletasks()
        x = (win.winfo_screenwidth() - width) // 2
        y = (win.winfo_screenheight() - height) // 3
        win.geometry(f"{width}x{height}+{x}+{y}")

    def _messagebox(self, kind: str, text: str) -> None:
        from tkinter import messagebox

        self._close_splash()
        parent = self._topmost_parent()
        getattr(messagebox, kind)("PATRICK", text, parent=parent)
        parent.destroy()

    def _topmost_parent(self):
        win = self._tk.Toplevel(self.root)
        win.withdraw()
        win.attributes("-topmost", True)
        return win

    # --- assistant de premier démarrage ----------------------------------------------------------------------------
    def _wizard(self) -> dict | None:
        self._close_splash()
        return SetupWizard(self.root).show()


class SetupWizard:
    """« Où sont tes données partagées ? » — dossier OneDrive, ou aucun."""

    def __init__(self, root) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk, self._ttk = tk, ttk
        self.result: dict | None = None
        self.win = win = tk.Toplevel(root)
        win.title("Bienvenue dans PATRICK")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self._later)
        outer = ttk.Frame(win, padding=(26, 20))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Bienvenue dans PATRICK", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(outer, wraplength=560, justify="left", font=("Segoe UI", 10),
                  text="Utilises-tu PATRICK sur plusieurs PC ? Choisis un dossier synchronisé (OneDrive, disque "
                       "réseau…) : PATRICK y dépose ses résultats et récupère ceux de tes autres PC. Rien n'est "
                       "jamais écrasé : les résultats des différents PC s'additionnent.").pack(anchor="w", pady=(6, 12))

        self.mode = tk.StringVar(value="folder")
        ttk.Radiobutton(outer, text="Oui, partager avec un dossier", value="folder", variable=self.mode,
                        command=self._refresh).pack(anchor="w")
        box = ttk.Frame(outer, padding=(24, 4, 0, 6))
        box.pack(fill="x")
        self.folder = tk.StringVar()
        self.entry = ttk.Combobox(box, textvariable=self.folder, width=62)
        self.entry.grid(row=0, column=0, sticky="we")
        self.browse = ttk.Button(box, text="Parcourir…", command=self._browse)
        self.browse.grid(row=0, column=1, padx=(8, 0))
        box.columnconfigure(0, weight=1)
        self.note = ttk.Label(box, text="", wraplength=540, justify="left", font=("Segoe UI", 9))
        self.note.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.reference = tk.BooleanVar(value=True)
        self.schedule = tk.BooleanVar(value=os.name == "nt")
        self.reference_box = ttk.Checkbutton(
            box, variable=self.reference, onvalue=True, offvalue=False,
            text="Ce PC est la référence du patrimoine (comptes, fonds)")
        self.reference_box.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.reference_hint = ttk.Label(
            box, wraplength=520, justify="left", font=("Segoe UI", 9), foreground="#6b7280",
            text="Il publie son patrimoine dans le dossier partagé; les autres PC l'adoptent. "
                 "Choisis donc un dossier privé.")
        self.reference_hint.grid(row=3, column=0, columnspan=2, sticky="w", padx=(22, 0))
        self.schedule_box = ttk.Checkbutton(
            box, variable=self.schedule, onvalue=True, offvalue=False,
            text="Publier ce PC automatiquement toutes les heures")
        self.schedule_box.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.reference_touched = False
        self.reference_box.configure(command=lambda: setattr(self, "reference_touched", True))

        ttk.Radiobutton(outer, text="Non, ce PC travaille seul (modifiable plus tard dans Réglages)", value="none",
                        variable=self.mode, command=self._refresh).pack(anchor="w", pady=(6, 0))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="Plus tard", command=self._later).pack(side="right", padx=(8, 0))
        self.ok = ttk.Button(buttons, text="Valider", command=self._validate)
        self.ok.pack(side="right")

        self._suggestions = share.suggest_folders()
        self.entry.configure(values=[s["path"] for s in self._suggestions])
        existing = next((s for s in self._suggestions if s["kind"] in ("current", "existing")), None)
        first = existing or next(iter(self._suggestions), None)
        if first:
            self.folder.set(first["path"])
        self._after_id = None
        self.folder.trace_add("write", lambda *_: self._schedule_inspect())
        self._refresh()
        self._inspect()
        win.update_idletasks()
        w, h = 620, win.winfo_reqheight()
        win.geometry(f"{w}x{h}+{(win.winfo_screenwidth() - w) // 2}+{(win.winfo_screenheight() - h) // 3}")

    def show(self) -> dict | None:
        self.win.grab_set()
        self.win.focus_force()
        self.win.wait_window()
        return self.result

    def _refresh(self) -> None:
        state = "normal" if self.mode.get() == "folder" else "disabled"
        for widget in (self.entry, self.browse, self.reference_box, self.schedule_box):
            widget.configure(state=state)
        self.note.configure(text="" if state == "disabled" else self.note.cget("text"))
        if state == "normal":
            self._inspect()

    def _browse(self) -> None:
        from tkinter import filedialog

        start = self.folder.get() if os.path.isdir(self.folder.get()) else str(Path.home())
        chosen = filedialog.askdirectory(parent=self.win, initialdir=start, title="Choisis le dossier partagé",
                                         mustexist=False)
        if chosen:
            self.folder.set(os.path.normpath(chosen))

    def _schedule_inspect(self) -> None:
        if self._after_id is not None:
            self.win.after_cancel(self._after_id)
        self._after_id = self.win.after(400, self._inspect)

    def _inspect(self) -> None:
        self._after_id = None
        if self.mode.get() != "folder":
            return
        path = self.folder.get().strip()
        if not path:
            self.note.configure(text="Indique ou choisis un dossier.", foreground="#6b7280")
            return
        info = share.inspect_folder(path)
        if info["has_share"]:
            when = (info["created_at"] or "")[:10]
            self.note.configure(foreground="#15803d", text=f"Partage PATRICK trouvé : {info['runs']} run(s), publié "
                                                           f"le {when}. Ce PC va le fusionner avec ses résultats.")
        elif info["exists"] and not info["writable"]:
            self.note.configure(foreground="#b91c1c", text="PATRICK ne peut pas écrire dans ce dossier.")
        elif info["exists"]:
            self.note.configure(foreground="#6b7280", text="Dossier vide : ce PC sera le premier à publier.")
        elif info["creatable"]:
            self.note.configure(foreground="#6b7280", text="Ce dossier sera créé. Ce PC sera le premier à publier.")
        else:
            self.note.configure(foreground="#b91c1c", text="Dossier introuvable (le dossier parent doit exister).")
        if not self.reference_touched:
            self.reference.set(share.default_wealth_reference(info))

    def _validate(self) -> None:
        from tkinter import messagebox

        if self.mode.get() == "none":
            self.result = {"folder": None, "wealth_reference": False, "schedule": False}
        else:
            try:
                folder = share.validate_folder(self.folder.get())
            except share.ShareError as exc:
                messagebox.showerror("PATRICK", str(exc), parent=self.win)
                return
            self.result = {"folder": folder, "wealth_reference": bool(self.reference.get()),
                           "schedule": bool(self.schedule.get())}
        self.win.destroy()

    def _later(self) -> None:
        self.result = None
        self.win.destroy()
