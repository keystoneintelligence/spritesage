"""Safe standard streams for windowed builds, with an opt-in Windows console."""

import os
import sys


def _open_windows_console():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleWindow.argtypes = []
    kernel.GetConsoleWindow.restype = wintypes.HWND
    kernel.AllocConsole.argtypes = []
    kernel.AllocConsole.restype = wintypes.BOOL
    kernel.FreeConsole.argtypes = []
    kernel.FreeConsole.restype = wintypes.BOOL
    kernel.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]
    kernel.SetConsoleTitleW.restype = wintypes.BOOL
    created = not kernel.GetConsoleWindow()
    if created and not kernel.AllocConsole():
        raise OSError("Could not open the Windows diagnostic console.")

    streams = {}
    try:
        for name, device, mode in (
            ("stdin", "CONIN$", "r"),
            ("stdout", "CONOUT$", "w"),
            ("stderr", "CONOUT$", "w"),
        ):
            # Preserve redirection when running source code from an existing terminal.
            if created or getattr(sys, name) is None:
                streams[name] = open(device, mode, buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        for stream in streams.values():
            stream.close()
        if created:
            kernel.FreeConsole()
        raise
    for name, stream in streams.items():
        setattr(sys, name, stream)
    if created:
        kernel.SetConsoleTitleW("Sprite Sage diagnostic console")


def prepare_standard_streams(argv=None):
    """Provide usable streams before importing GUI or inference libraries."""
    arguments = sys.argv if argv is None else argv
    if sys.platform == "win32" and "--console" in arguments:
        _open_windows_console()
    for name, mode in (("stdin", "r"), ("stdout", "w"), ("stderr", "w")):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, mode, encoding="utf-8"))
