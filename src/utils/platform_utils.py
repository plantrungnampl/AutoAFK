"""Platform detection and OS-conditional subprocess helpers.

This is the ONLY module in AutoAFK that may inspect ``platform.system()``
or ``sys.platform``, and the ONLY module that may import Windows-only
symbols (``STARTUPINFO``, ``CREATE_NO_WINDOW``, ``CREATE_NEW_CONSOLE``,
``CREATE_NEW_PROCESS_GROUP``, ``win32gui``, ``win32con``).

All other modules MUST call into the helpers exposed here instead of
branching on the platform themselves. This keeps platform-conditional
behavior auditable (a grep for ``platform.system()`` outside this file
becomes a lint signal) and makes Linux startup safe (Windows-only
symbols are imported lazily inside the helper functions, so they are
never touched on Linux Python builds).
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
from typing import Literal

logger = logging.getLogger(__name__)

Platform = Literal['windows', 'linux', 'unsupported']

# Module-level flag so the "unsupported platform" warning fires exactly
# once per process even though detect_platform() is called many times
# (every is_windows() / is_linux_like() call routes through it).
_unsupported_warning_emitted = False


def detect_platform() -> Platform:
    """Return the canonical platform name.

    Returns ``'windows'`` on Windows, ``'linux'`` on Linux, and
    ``'unsupported'`` (with a one-time warning naming the detected
    platform) on anything else. Unsupported platforms (notably macOS)
    fall back to the Linux code paths in the rest of the codebase.

    Requirements: 1.1, 1.2, 1.3, 1.4.
    """
    global _unsupported_warning_emitted
    name = platform.system()
    if name == 'Windows':
        return 'windows'
    if name == 'Linux':
        return 'linux'
    if not _unsupported_warning_emitted:
        logger.warning(
            "Unsupported platform '%s' detected; falling back to Linux "
            "code paths. This configuration is not validated.",
            name,
        )
        _unsupported_warning_emitted = True
    return 'unsupported'


def is_windows() -> bool:
    """True iff running on Windows. Requirement 1.5."""
    return detect_platform() == 'windows'


def is_linux_like() -> bool:
    """True on Linux and on the unsupported fallback. Requirement 1.5."""
    return detect_platform() != 'windows'


# ---------- subprocess kwarg helpers ---------------------------------------

def subprocess_hidden_kwargs() -> dict:
    """Kwargs for ``subprocess.Popen`` calls that must NOT show a console.

    On Windows: ``startupinfo=STARTUPINFO()``, ``creationflags=CREATE_NO_WINDOW``.
    On Linux/unsupported: empty dict (no console is shown by default).

    Imports are deliberately performed inside the function so that
    ``import platform_utils`` succeeds on Linux Python builds where
    these symbols do not exist on the ``subprocess`` module.

    Requirements: 3.1, 3.2, 3.5.
    """
    if not is_windows():
        return {}
    # Imported lazily: these symbols only exist on Windows builds of CPython.
    from subprocess import STARTUPINFO, CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return {
        'startupinfo': STARTUPINFO(),
        'creationflags': CREATE_NO_WINDOW,
    }


def subprocess_detached_kwargs() -> dict:
    """Kwargs to launch a child that survives the parent and detaches.

    On Windows: ``CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP`` so the
    user sees the updater's progress window and the child survives
    ``AutoAFK.exe`` exiting.
    On Linux/unsupported: ``start_new_session=True`` (POSIX equivalent
    of detaching from the parent's process group).

    Imports are deliberately performed inside the function so that
    ``import platform_utils`` succeeds on Linux Python builds.

    Requirements: 3.3, 3.4, 3.5.
    """
    if is_windows():
        # Imported lazily: these symbols only exist on Windows builds.
        from subprocess import (  # type: ignore[attr-defined]
            CREATE_NEW_CONSOLE,
            CREATE_NEW_PROCESS_GROUP,
        )
        return {'creationflags': CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


# ---------- ADB resolution -------------------------------------------------

class AdbNotFoundError(RuntimeError):
    """Raised on Linux when no ``adb`` executable is on ``$PATH``."""


def resolve_adb_path() -> str:
    """Return the path to the adb executable to use.

    Windows: prefer the bundled ``adb.exe`` next to ``sys.executable``
    when frozen, otherwise prefer ``<repo_root>/adb.exe``, otherwise fall
    back to ``shutil.which('adb')``, and finally fall back to the literal
    string ``'adb'`` (preserves the existing fallback behavior).

    Linux/unsupported: return ``shutil.which('adb')`` if present,
    otherwise raise ``AdbNotFoundError`` with a message naming ``adb``,
    the ``android-tools`` package, and the example
    ``sudo pacman -S android-tools`` install command.

    Requirements: 2.1, 2.2, 2.3, 2.4.
    """
    if is_windows():
        # Frozen build: adb.exe sits next to AutoAFK.exe.
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            bundled = os.path.join(exe_dir, 'adb.exe')
            if os.path.exists(bundled):
                return bundled
        # Dev mode: adb.exe at repo root (this file lives at
        # src/utils/platform_utils.py, so repo_root is three dirs up).
        repo_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        bundled = os.path.join(repo_root, 'adb.exe')
        if os.path.exists(bundled):
            return bundled
        # Last resort: a system adb on PATH, then the literal 'adb' so
        # the existing "let subprocess raise" behavior is preserved.
        system_adb = shutil.which('adb')
        if system_adb:
            return system_adb
        return 'adb'

    # Linux (and unsupported fallback).
    system_adb = shutil.which('adb')
    if system_adb:
        return system_adb
    raise AdbNotFoundError(
        "adb executable not found on $PATH. "
        "Install the 'android-tools' package via your system package "
        "manager (example: 'sudo pacman -S android-tools' on CachyOS/Arch)."
    )


# ---------- Window management ---------------------------------------------

def minimize_emulator_windows() -> None:
    """Minimize BlueStacks / HD-Player top-level windows.

    Windows: enumerate top-level windows via ``win32gui`` and minimize
    those whose title contains ``BlueStacks`` or ``HD-Player``. Any
    exception (including ``ImportError`` when ``pywin32`` is not
    installed) is swallowed at debug level, preserving the existing
    "never crash on minimize failure" behavior.

    Linux/unsupported: log an INFO message stating the operation is not
    supported on this platform and return without raising.

    Requirements: 4.1, 4.2, 4.3, 4.4.
    """
    if not is_windows():
        logger.info(
            "Window minimization is not supported on this platform; skipping."
        )
        return
    try:
        # Imported lazily: win32gui / win32con are not available on Linux
        # and are only an explicit dependency on Windows.
        import win32gui  # type: ignore[import-not-found]
        import win32con  # type: ignore[import-not-found]

        def _callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if 'BlueStacks' in title or 'HD-Player' in title:
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

        win32gui.EnumWindows(_callback, None)
    except Exception as e:
        # Match existing behavior: never crash on minimize failure.
        logger.debug("Could not minimize emulator window: %s", e)
