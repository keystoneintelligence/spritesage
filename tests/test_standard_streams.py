"""Windowed startup must work without streams or an implicit console."""

import io
import sys
from types import SimpleNamespace

import pytest

from spritesage import standard_streams


def test_windowed_startup_supplies_safe_streams_without_opening_console(monkeypatch):
    opened = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(standard_streams, "_open_windows_console", lambda: opened.append(True))
    for name in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(sys, name, None)
    standard_streams.prepare_standard_streams(["spritesage.exe"])
    try:
        assert opened == []
        assert sys.stdin.read() == ""
        print("Diagnostic output is safe without a console")
        sys.stdout.flush()
        sys.stderr.write("Safe error output\n")
        sys.stderr.flush()
    finally:
        for name in ("stdin", "stdout", "stderr"):
            getattr(sys, name).close()


def test_console_requires_explicit_launch_option(monkeypatch):
    opened = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(standard_streams, "_open_windows_console", lambda: opened.append(True))
    original = (sys.stdin, sys.stdout, sys.stderr)
    standard_streams.prepare_standard_streams(["spritesage.exe", "--console"])
    assert opened == [True]
    assert (sys.stdin, sys.stdout, sys.stderr) == original


def test_other_platforms_preserve_streams_without_windows_calls(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        standard_streams,
        "_open_windows_console",
        lambda: pytest.fail("Windows API invoked on another platform"),
    )
    original = (sys.stdin, sys.stdout, sys.stderr)
    standard_streams.prepare_standard_streams(["spritesage", "--console"])
    assert (sys.stdin, sys.stdout, sys.stderr) == original


@pytest.fixture
def windows_api(monkeypatch):
    import ctypes

    class Function:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def __call__(self, *args):
            self.calls.append(args)
            return self.result

    api = SimpleNamespace(
        GetConsoleWindow=Function(0),
        AllocConsole=Function(1),
        FreeConsole=Function(1),
        SetConsoleTitleW=Function(1),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: api, raising=False)
    return api


def test_requested_console_opens_devices_and_routes_output(monkeypatch, windows_api):
    devices = []

    def open_device(path, mode, **kwargs):
        stream = io.StringIO()
        devices.append((path, mode, stream))
        return stream

    for name in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(sys, name, None)
    monkeypatch.setattr(standard_streams, "open", open_device, raising=False)
    standard_streams._open_windows_console()
    assert windows_api.AllocConsole.calls == [()]
    assert windows_api.SetConsoleTitleW.calls == [("Sprite Sage diagnostic console",)]
    assert [(path, mode) for path, mode, stream in devices] == [
        ("CONIN$", "r"),
        ("CONOUT$", "w"),
        ("CONOUT$", "w"),
    ]
    print("Visible diagnostic")
    sys.stderr.write("Visible error")
    assert devices[1][2].getvalue() == "Visible diagnostic\n"
    assert devices[2][2].getvalue() == "Visible error"


def test_existing_terminal_and_redirection_are_preserved(monkeypatch, windows_api):
    windows_api.GetConsoleWindow.result = 123
    monkeypatch.setattr(
        standard_streams,
        "open",
        lambda *args, **kwargs: pytest.fail("Existing streams replaced"),
        raising=False,
    )
    original = (sys.stdin, sys.stdout, sys.stderr)
    standard_streams._open_windows_console()
    assert not windows_api.AllocConsole.calls
    assert not windows_api.SetConsoleTitleW.calls
    assert (sys.stdin, sys.stdout, sys.stderr) == original


def test_failed_device_open_releases_only_the_new_console(monkeypatch, windows_api):
    def fail(*args, **kwargs):
        raise OSError("Console unavailable")

    monkeypatch.setattr(standard_streams, "open", fail, raising=False)
    with pytest.raises(OSError):
        standard_streams._open_windows_console()
    assert windows_api.FreeConsole.calls == [()]


def test_failed_console_allocation_leaves_streams_untouched(monkeypatch, windows_api):
    windows_api.AllocConsole.result = 0
    original = (sys.stdin, sys.stdout, sys.stderr)
    with pytest.raises(OSError, match="Could not open"):
        standard_streams._open_windows_console()
    assert (sys.stdin, sys.stdout, sys.stderr) == original
    assert not windows_api.FreeConsole.calls
