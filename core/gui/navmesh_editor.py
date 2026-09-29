"""The Navmesh bar entry: the navmesh editor's server, its status card, and the pin folder.

The editor is cellview (`tools/cellview/server.py`), run as a child of this
window on a free port.  Its first line is `cellview: <url>`; a reader thread
keeps that URL and the latest line, which the status card polls.  The server
lives exactly as long as the window: closing the window stops it, and the
GUI's kill-on-close job catches a crash.  The Transplant corpus is never
offered here -- it needs reference data only a developer checkout has.

See: docs/commentary/tes5_import_navmesh.md#navmesh-editor-in-the-gui
"""

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from core.gui.config import (
    CLR,
    NAVMESH_PINS_CONFIG_KEY,
    REPO_ROOT,
    navmesh_pins_dir,
    save_setting,
)
from core.gui.menubar_behavior import add_tipped_command, enable_tips
from core.gui.widgets import open_folder, open_url
from core.process_job import kill_process_tree
from core.subprocess_flags import POPEN_FLAGS

#: The editor's server script.
SERVER = REPO_ROOT / "tools" / "cellview" / "server.py"

#: How often the status card re-reads the server's state, in milliseconds.
POLL_MS = 300


# ---------------------------------------------------------------------------
#  The server
# ---------------------------------------------------------------------------

class EditorServer(object):
    """The one editor server this window runs."""

    def __init__(self):
        """Nothing running yet."""
        self.proc = None
        self.url = ""
        self.last = ""
        self.browser_opened = False

    def running(self) -> bool:
        """True while the server process is alive."""
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        """Start the server on a free port, saving pins to the chosen folder."""
        if self.running():
            return
        self.url, self.last, self.browser_opened = "", "starting…", False
        self.proc = subprocess.Popen(
            [sys.executable, "-u", str(SERVER), "--port", "0", "--no-browser",
             "--pins", navmesh_pins_dir()],
            cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors="replace",
            **POPEN_FLAGS)
        threading.Thread(target=self._read, args=(self.proc,),
                         daemon=True).start()

    def _read(self, proc) -> None:
        """Keep the URL from the banner and the latest line the server printed."""
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("cellview: ") and not self.url:
                self.url = line.split(" ", 1)[1]
            if line:
                self.last = line

    def stop(self) -> None:
        """Stop the server and anything it started, such as a collision scan."""
        if self.running():
            kill_process_tree(self.proc.pid)
        self.proc = None
        self.url = ""
        self.last = ""

    def state(self) -> tuple:
        """(headline, color) describing the server right now."""
        if self.running():
            return (("Running", CLR["green"]) if self.url
                    else ("Starting…", CLR["yellow"]))
        if self.proc is not None:
            return "Stopped unexpectedly", CLR["red"]
        return "Stopped", CLR["subtext"]


# ---------------------------------------------------------------------------
#  The status card
# ---------------------------------------------------------------------------

def _label(card, text="", fg=None, font=("Segoe UI", 9), **kw):
    """One left-aligned label on the card, packed."""
    lbl = tk.Label(card, text=text, bg=CLR["panel"], fg=fg or CLR["subtext"],
                   font=font, justify=tk.LEFT, anchor="w", wraplength=400, **kw)
    lbl.pack(anchor="w", padx=16, pady=(0, 6))
    return lbl


def _card_widgets(app, server) -> dict:
    """Build the card's labels; returns them by role."""
    card = tk.Frame(app.outer, bg=CLR["panel"],
                    highlightbackground=CLR["border"], highlightthickness=1)
    tk.Label(card, text="Navmesh Editor", bg=CLR["panel"], fg=CLR["text"],
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16,
                                                 pady=(14, 0))
    ttk.Separator(card, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=16, pady=8)
    out = {'card': card,
           'status': _label(card, font=("Segoe UI", 13, "bold")),
           'link': _label(card, fg=CLR["accent_hover"],
                          font=("Segoe UI", 9, "underline"), cursor="hand2"),
           'last': _label(card),
           'pins': _label(card, "Pins are saved to:\n" + navmesh_pins_dir())}
    out['link'].bind("<Button-1>",
                     lambda _e: server.url and open_url(server.url))
    return out


def _card_buttons(w, server) -> dict:
    """The Open / Stop-or-Start / Close row; returns the buttons by role."""
    row = tk.Frame(w['card'], bg=CLR["panel"])
    row.pack(fill=tk.X, padx=16, pady=(6, 14))

    def _close():
        """Tear the card down; the server keeps running."""
        w['card'].grab_release()
        w['card'].destroy()

    def _toggle():
        """Stop a running server, or start a stopped one."""
        if server.running():
            server.stop()
        else:
            server.start()

    close = ttk.Button(row, text="Close", width=10, command=_close)
    close.pack(side=tk.RIGHT, padx=(6, 0))
    toggle = ttk.Button(row, text="Stop Server", width=12, command=_toggle)
    toggle.pack(side=tk.RIGHT, padx=(6, 0))
    browse = ttk.Button(row, text="Open in Browser", width=15,
                        style="Accent.TButton",
                        command=lambda: server.url and open_url(server.url))
    browse.pack(side=tk.RIGHT, padx=(6, 0))
    w['card'].bind("<Escape>", lambda _e: _close())
    return {'toggle': toggle, 'browse': browse}


def _refresh(w, b, server) -> None:
    """Redraw the card from the server's state, open the browser once, poll again."""
    if not w['card'].winfo_exists():
        return
    text, color = server.state()
    w['status'].configure(text=text, fg=color)
    w['link'].configure(text=server.url)
    w['last'].configure(text=server.last)
    b['toggle'].configure(text="Stop Server" if server.running()
                          else "Start Server")
    b['browse'].configure(state="normal" if server.url else "disabled")
    if server.url and not server.browser_opened:
        server.browser_opened = True
        open_url(server.url)
    w['card'].after(POLL_MS, lambda: _refresh(w, b, server))


def show_status(app, server) -> None:
    """Modal card with the server's live status, its address and controls."""
    w = _card_widgets(app, server)
    b = _card_buttons(w, server)
    _refresh(w, b, server)
    w['card'].update_idletasks()
    w['card'].place(in_=app.outer, anchor="center", relx=0.5, rely=0.5)
    w['card'].lift()
    w['card'].focus_set()
    w['card'].grab_set()
    app.root.wait_window(w['card'])


# ---------------------------------------------------------------------------
#  The menu
# ---------------------------------------------------------------------------

def _open_editor(app, server) -> None:
    """Start the server if needed and show its status."""
    server.start()
    show_status(app, server)


def _choose_pins_dir(app, server) -> None:
    """Pick the pin save folder; a running server restarts to use it."""
    current = navmesh_pins_dir()
    got = filedialog.askdirectory(
        parent=app.root, title="Navmesh pin save location",
        initialdir=current if os.path.isdir(current) else str(REPO_ROOT))
    if not got:
        return
    save_setting(NAVMESH_PINS_CONFIG_KEY, os.path.normpath(got))
    if server.running():
        server.stop()
        server.start()
    app.info("Navmesh Pins",
             f"Pins are now saved to:\n\n{navmesh_pins_dir()}\n\n"
             "Imports read them from there, over the pins that ship with "
             "the converter.")


def _open_pins_dir(app) -> None:
    """Reveal the pin save folder, creating it on first use."""
    path = navmesh_pins_dir()
    os.makedirs(path, exist_ok=True)
    open_folder(app, path, "Pins folder")


def _stop_on_close(app, server) -> None:
    """Stop the server before the window is destroyed."""
    def _close():
        """Stop the server, then close the window."""
        server.stop()
        app.root.destroy()
    app.root.protocol("WM_DELETE_WINDOW", _close)


def build_menu(app, menubutton) -> None:
    """Navmesh: open the editor, choose where pins are saved, open that folder."""
    server = EditorServer()
    menu = menubutton("Navmesh")
    enable_tips(menu)
    add_tipped_command(
        menu, "Open Navmesh Editor", lambda: _open_editor(app, server),
        "Edit a converted plugin's navmesh in your browser and pin the fixes "
        "so every later import keeps them")
    menu.add_separator()
    add_tipped_command(
        menu, "Pin Save Location…", lambda: _choose_pins_dir(app, server),
        "Choose the folder your pins are saved to; imports read them from "
        "there")
    add_tipped_command(
        menu, "Open Pins Folder", lambda: _open_pins_dir(app),
        "Open the folder your pins are saved to, to back them up or share "
        "them")
    _stop_on_close(app, server)
