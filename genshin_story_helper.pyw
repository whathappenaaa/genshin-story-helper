"""A small, dependency-free Windows input helper for Genshin story scenes.

The program deliberately uses only normal Windows input simulation. It does not
read or modify game memory, attach to the game process, or bypass anti-cheat.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import messagebox

try:
    import customtkinter as ctk
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    ctk = None
    pystray = None
    Image = None
    ImageDraw = None


APP_TITLE = "把你砌进神像里"
GAME_PROCESSES = {"yuanshen.exe", "genshinimpact.exe"}
GAME_WINDOW_TITLES = {"原神", "genshin impact"}

VK_F = 0x46
VK_W = 0x57
VK_MENU = 0x12
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F12 = 0x7B

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

MODE_PRESS_F = "press_f"
MODE_CLICK = "click"
MODE_HOLD_W = "hold_w"

MODE_NAMES = {
    MODE_PRESS_F: "连按 F",
    MODE_CLICK: "连点鼠标左键",
    MODE_HOLD_W: "长按 W",
}

DEFAULT_SETTINGS = {
    "interval_ms": 120,
    "background_mode": False,
    "auto_focus": True,
    "press_key": "F",
    "hold_key": "W",
    "hotkeys": {
        "press": "F6",
        "click": "F7",
        "hold": "F8",
        "stop": "F12",
    },
}

KEY_ALIASES = {
    "SPACE": 0x20,
    "空格": 0x20,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "回车": 0x0D,
    "TAB": 0x09,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
}


if sys.platform != "win32":
    raise SystemExit("此工具只支持 Windows。")


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

ULONG_PTR = wintypes.WPARAM
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class INPUT_UNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = (("type", wintypes.DWORD), ("data", INPUT_UNION))


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ULONG_PTR),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    )


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PostMessageW.restype = wintypes.BOOL
user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
user32.FindWindowW.restype = wintypes.HWND
user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.GetClientRect.restype = wintypes.BOOL
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = (wintypes.HWND,)
user32.BringWindowToTop.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
user32.AttachThreadInput.restype = wintypes.BOOL

kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
kernel32.Process32NextW.restype = wintypes.BOOL
shell32.IsUserAnAdmin.restype = wintypes.BOOL


def _send_input(item: INPUT) -> bool:
    return user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT)) == 1


def send_key(vk_code: int, is_down: bool) -> bool:
    scan_code = user32.MapVirtualKeyW(vk_code, 0)
    flags = KEYEVENTF_SCANCODE | (0 if is_down else KEYEVENTF_KEYUP)
    item = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan_code, flags, 0, 0))
    return _send_input(item)


def press_key(vk_code: int) -> None:
    if send_key(vk_code, True):
        time.sleep(0.018)
        send_key(vk_code, False)


def click_left() -> None:
    down = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0))
    up = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0))
    if _send_input(down):
        time.sleep(0.012)
        _send_input(up)


def foreground_window_info() -> tuple[str, str]:
    """Return (process filename, window title) for the foreground window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""

    title_length = user32.GetWindowTextLengthW(hwnd)
    title_buffer = ctypes.create_unicode_buffer(title_length + 1)
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))

    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    process_handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value
    )
    if not process_handle:
        return "", title_buffer.value

    try:
        capacity = wintypes.DWORD(32768)
        path_buffer = ctypes.create_unicode_buffer(capacity.value)
        if kernel32.QueryFullProcessImageNameW(
            process_handle, 0, path_buffer, ctypes.byref(capacity)
        ):
            return os.path.basename(path_buffer.value).lower(), title_buffer.value
    finally:
        kernel32.CloseHandle(process_handle)

    return "", title_buffer.value


def is_game_foreground() -> bool:
    process_name, title = foreground_window_info()
    return (
        process_name in GAME_PROCESSES
        or title.strip().lower() in GAME_WINDOW_TITLES
    )


def find_game_processes() -> list[tuple[int, str]]:
    """Find Genshin processes without requiring permission to open their handles."""
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return []

    matches: list[tuple[int, str]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            executable = entry.szExeFile.lower()
            if executable in GAME_PROCESSES:
                matches.append((int(entry.th32ProcessID), entry.szExeFile))
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return matches


def is_elevated() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except OSError:
        return False


def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def settings_path() -> str:
    folder = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "GenshinStoryHelper")
    return os.path.join(folder, "settings.json")


def load_settings() -> dict:
    settings = {
        **DEFAULT_SETTINGS,
        "hotkeys": dict(DEFAULT_SETTINGS["hotkeys"]),
    }
    try:
        with open(settings_path(), "r", encoding="utf-8") as settings_file:
            stored = json.load(settings_file)
        for key in ("interval_ms", "background_mode", "auto_focus", "press_key", "hold_key"):
            if key in stored:
                settings[key] = stored[key]
        if isinstance(stored.get("hotkeys"), dict):
            settings["hotkeys"].update(stored["hotkeys"])
    except (OSError, ValueError, TypeError):
        pass
    settings["interval_ms"] = max(60, min(int(settings["interval_ms"]), 600))
    return settings


def save_settings(settings: dict) -> None:
    try:
        path = settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as settings_file:
            json.dump(settings, settings_file, ensure_ascii=False, indent=2)
    except OSError:
        pass


def key_name_to_vk(key_name: str) -> int:
    normalized = key_name.strip().upper().replace(" ", "")
    if normalized in KEY_ALIASES:
        return KEY_ALIASES[normalized]
    if len(normalized) == 1 and normalized in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        return ord(normalized)
    function_match = re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", normalized)
    if function_match:
        return 0x70 + int(function_match.group(1)) - 1
    raise ValueError(f"不支持的按键：{key_name}")


def parse_hotkey(specification: str) -> tuple[int, int]:
    tokens = [item.strip().upper() for item in specification.split("+") if item.strip()]
    if not tokens:
        raise ValueError("快捷键不能为空")
    modifiers = MOD_NOREPEAT
    key_tokens: list[str] = []
    for token in tokens:
        if token in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif token == "ALT":
            modifiers |= MOD_ALT
        elif token == "SHIFT":
            modifiers |= MOD_SHIFT
        elif token in {"WIN", "WINDOWS"}:
            modifiers |= MOD_WIN
        else:
            key_tokens.append(token)
    if len(key_tokens) != 1:
        raise ValueError(f"快捷键必须包含一个主键：{specification}")
    return modifiers, key_name_to_vk(key_tokens[0])


def find_game_window() -> int:
    for title in ("原神", "Genshin Impact"):
        window = user32.FindWindowW(None, title)
        if window:
            return int(window)

    game_process_ids = {process_id for process_id, _ in find_game_processes()}
    if not game_process_ids:
        return 0

    matching_windows: list[int] = []

    @WNDENUMPROC
    def collect_game_window(window: int, _parameter: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        if process_id.value not in game_process_ids or not user32.IsWindowVisible(window):
            return True
        if user32.GetWindowTextLengthW(window) > 0:
            matching_windows.append(int(window))
        return True

    user32.EnumWindows(collect_game_window, 0)
    if matching_windows:
        return matching_windows[0]
    return 0


def activate_game_window() -> bool:
    window = find_game_window()
    if not window:
        return False

    if int(user32.GetForegroundWindow() or 0) == window:
        return True

    current_thread = kernel32.GetCurrentThreadId()
    foreground_window = user32.GetForegroundWindow()
    foreground_thread = (
        user32.GetWindowThreadProcessId(foreground_window, None)
        if foreground_window
        else 0
    )
    attached = bool(
        foreground_thread
        and foreground_thread != current_thread
        and user32.AttachThreadInput(current_thread, foreground_thread, True)
    )
    try:
        user32.ShowWindow(window, 9)  # SW_RESTORE
        user32.BringWindowToTop(window)
        user32.SetForegroundWindow(window)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)

    # Windows may reject focus changes from a background helper even when the
    # request came from a registered hotkey. Retry only after detaching input
    # queues; a harmless Alt tap grants foreground-switch permission.
    if int(user32.GetForegroundWindow() or 0) != window:
        send_key(VK_MENU, True)
        send_key(VK_MENU, False)
        user32.BringWindowToTop(window)
        user32.SetForegroundWindow(window)

    time.sleep(0.05)
    return int(user32.GetForegroundWindow() or 0) == window


def post_background_key(window: int, vk_code: int, is_down: bool) -> bool:
    scan_code = user32.MapVirtualKeyW(vk_code, 0)
    message = WM_KEYDOWN if is_down else WM_KEYUP
    message_data = 1 | (scan_code << 16)
    if not is_down:
        message_data |= (1 << 30) | (1 << 31)
    return bool(user32.PostMessageW(window, message, vk_code, message_data))


def press_background_key(window: int, vk_code: int) -> None:
    if post_background_key(window, vk_code, True):
        time.sleep(0.018)
        post_background_key(window, vk_code, False)


def click_background_center(window: int) -> None:
    client = wintypes.RECT()
    if not user32.GetClientRect(window, ctypes.byref(client)):
        return
    x = max(1, (client.right - client.left) // 2)
    y = max(1, (client.bottom - client.top) // 2)
    coordinates = (y << 16) | (x & 0xFFFF)
    if user32.PostMessageW(window, WM_LBUTTONDOWN, MK_LBUTTON, coordinates):
        time.sleep(0.012)
        user32.PostMessageW(window, WM_LBUTTONUP, 0, coordinates)


class AutomationEngine:
    def __init__(
        self,
        interval_ms: int,
        background_mode: bool,
        press_vk: int,
        hold_vk: int,
    ) -> None:
        self._lock = threading.Lock()
        self._input_lock = threading.Lock()
        self._active_modes: set[str] = set()
        self._interval_seconds = max(0.06, min(interval_ms / 1000.0, 0.6))
        self._background_mode = background_mode
        self._press_vk = press_vk
        self._hold_vk = hold_vk
        self._held_vk = 0
        self._held_window = 0
        self._held_in_background = False
        self._shutdown = threading.Event()
        self._worker = threading.Thread(target=self._run, name="input-worker", daemon=True)
        self._worker.start()

    def snapshot(self) -> tuple[frozenset[str], float, bool, int, int]:
        with self._lock:
            return (
                frozenset(self._active_modes),
                self._interval_seconds,
                self._background_mode,
                self._press_vk,
                self._hold_vk,
            )

    def set_mode(self, mode: str | None) -> None:
        with self._lock:
            self._active_modes = set() if mode is None else {mode}

    def toggle(self, mode: str) -> frozenset[str]:
        with self._lock:
            if mode in self._active_modes:
                self._active_modes.remove(mode)
            else:
                self._active_modes.add(mode)
            return frozenset(self._active_modes)

    def set_interval_ms(self, interval_ms: int) -> None:
        with self._lock:
            self._interval_seconds = max(0.06, min(interval_ms / 1000.0, 2.0))

    def set_background_mode(self, enabled: bool) -> None:
        with self._lock:
            self._background_mode = enabled

    def set_action_keys(self, press_vk: int, hold_vk: int) -> None:
        self.stop()
        with self._lock:
            self._press_vk = press_vk
            self._hold_vk = hold_vk

    def stop(self) -> None:
        self.set_mode(None)
        self._release_hold()

    def _release_hold(self) -> None:
        with self._input_lock:
            if not self._held_vk:
                return
            if self._held_in_background and self._held_window:
                post_background_key(self._held_window, self._held_vk, False)
            else:
                send_key(self._held_vk, False)
            self._held_vk = 0
            self._held_window = 0
            self._held_in_background = False

    def _ensure_hold(self, vk_code: int, background: bool, window: int) -> None:
        with self._input_lock:
            if (
                self._held_vk == vk_code
                and self._held_in_background == background
                and (not background or self._held_window == window)
            ):
                return
        self._release_hold()
        succeeded = (
            post_background_key(window, vk_code, True)
            if background
            else send_key(vk_code, True)
        )
        if succeeded:
            with self._input_lock:
                self._held_vk = vk_code
                self._held_window = window if background else 0
                self._held_in_background = background

    def _run(self) -> None:
        while not self._shutdown.is_set():
            active_modes, interval, background_mode, press_vk, hold_vk = self.snapshot()
            game_window = find_game_window()
            output_allowed = bool(game_window) if background_mode else is_game_foreground()

            if MODE_HOLD_W in active_modes and output_allowed:
                self._ensure_hold(hold_vk, background_mode, game_window)
            else:
                self._release_hold()

            repeated_input = False
            if MODE_PRESS_F in active_modes and output_allowed:
                if background_mode:
                    press_background_key(game_window, press_vk)
                else:
                    press_key(press_vk)
                repeated_input = True
            if MODE_CLICK in active_modes and output_allowed:
                if background_mode:
                    click_background_center(game_window)
                else:
                    click_left()
                repeated_input = True

            self._shutdown.wait(interval if repeated_input else 0.04)

        self._release_hold()

    def close(self) -> None:
        self.stop()
        self._shutdown.set()
        self._worker.join(timeout=1.0)
        self._release_hold()


class HotkeyListener:
    ACTIONS = {
        1: ("press", MODE_PRESS_F),
        2: ("click", MODE_CLICK),
        3: ("hold", MODE_HOLD_W),
        4: ("stop", None),
    }

    def __init__(self, event_queue: queue.Queue[str | None], bindings: dict[str, str]) -> None:
        self._event_queue = event_queue
        self._bindings = dict(bindings)
        self._thread_id = 0
        self._registered_ids: list[int] = []
        self._ready = threading.Event()
        self.error = ""
        self._thread = threading.Thread(target=self._run, name="hotkey-listener", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        failures: list[str] = []
        for hotkey_id, (binding_name, _) in self.ACTIONS.items():
            specification = self._bindings.get(binding_name, "")
            try:
                modifiers, vk_code = parse_hotkey(specification)
            except ValueError as error:
                failures.append(str(error))
                continue
            if user32.RegisterHotKey(None, hotkey_id, modifiers, vk_code):
                self._registered_ids.append(hotkey_id)
            else:
                failures.append(f"{specification} 已被其他程序占用")
        if failures:
            self.error = "；".join(failures)
        self._ready.set()

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY:
                hotkey = self.ACTIONS.get(int(message.wParam))
                if hotkey is not None:
                    self._event_queue.put(hotkey[1])

        for hotkey_id in self._registered_ids:
            user32.UnregisterHotKey(None, hotkey_id)

    def close(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=1.0)


class LegacyStoryHelperApp:
    COLORS = {
        "window": "#09111F",
        "card": "#121D2E",
        "card_hover": "#18263A",
        "border": "#24344D",
        "text": "#F4F7FB",
        "muted": "#8FA2BC",
        "blue": "#4B8DFF",
        "blue_hover": "#3C79DF",
        "green": "#2DD4A0",
        "amber": "#F5B942",
        "red": "#F26767",
        "purple": "#A78BFA",
    }

    def __init__(self, root) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("820x760")
        self.root.resizable(False, False)
        self.root.configure(fg_color=self.COLORS["window"])
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.root.bind("<Unmap>", self._on_window_unmap)
        self._closing = False
        self._tray_notice_shown = False
        self._tray_icon = None
        self._last_ready: bool | None = None
        self._hotkey_after_id = None
        self._status_after_id = None
        self._unmap_after_id = None
        self._warning_after_id = None

        self.engine = AutomationEngine()
        self.hotkey_events: queue.Queue[str | None] = queue.Queue()
        self.hotkeys = HotkeyListener(self.hotkey_events)

        self.interval_value = tk.DoubleVar(value=120)
        self.game_only = tk.BooleanVar(value=True)
        self.mode_buttons = {}

        self._build_ui()
        self._setup_tray()
        self._hotkey_after_id = self.root.after(50, self._poll_hotkeys)
        self._status_after_id = self.root.after(250, self._refresh_status)

        if self.hotkeys.error:
            self._warning_after_id = self.root.after(
                200,
                lambda: messagebox.showwarning("热键注册失败", self.hotkeys.error),
            )

    def _build_ui(self) -> None:
        outer = ctk.CTkFrame(self.root, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=30, pady=24)

        header = ctk.CTkFrame(outer, fg_color="transparent", height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.pack(side="left", fill="y")
        ctk.CTkLabel(
            title_group,
            text="把你砌进神像里",
            font=("Microsoft YaHei UI", 25, "bold"),
            text_color=self.COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="后台驻留 · 全局热键 · F12 随时急停",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["muted"],
        ).pack(anchor="w", pady=(3, 0))
        self.permission_badge = ctk.CTkLabel(
            header,
            text="检查权限中",
            width=126,
            height=34,
            corner_radius=17,
            fg_color="#27354B",
            text_color=self.COLORS["muted"],
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        self.permission_badge.pack(side="right", pady=(5, 0))

        connection = ctk.CTkFrame(
            outer,
            height=132,
            corner_radius=18,
            fg_color=self.COLORS["card"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        connection.pack(fill="x", pady=(14, 12))
        connection.pack_propagate(False)
        connection_left = ctk.CTkFrame(connection, fg_color="transparent")
        connection_left.pack(side="left", fill="both", expand=True, padx=22, pady=18)
        ctk.CTkLabel(
            connection_left,
            text="游戏连接状态",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["muted"],
        ).pack(anchor="w")
        self.connection_badge = ctk.CTkLabel(
            connection_left,
            text="● 正在检测原神…",
            font=("Microsoft YaHei UI", 20, "bold"),
            text_color=self.COLORS["muted"],
        )
        self.connection_badge.pack(anchor="w", pady=(5, 0))
        self.connection_detail = ctk.CTkLabel(
            connection_left,
            text="请稍候",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["muted"],
        )
        self.connection_detail.pack(anchor="w", pady=(5, 0))
        self.process_detail = ctk.CTkLabel(
            connection,
            text="PID  —",
            width=170,
            height=70,
            corner_radius=14,
            fg_color="#0C1626",
            text_color=self.COLORS["muted"],
            font=("Consolas", 11),
        )
        self.process_detail.pack(side="right", padx=20)

        controls = ctk.CTkFrame(
            outer,
            corner_radius=18,
            fg_color=self.COLORS["card"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        controls.pack(fill="x", pady=(0, 12))
        control_header = ctk.CTkFrame(controls, fg_color="transparent")
        control_header.pack(fill="x", padx=22, pady=(17, 12))
        ctk.CTkLabel(
            control_header,
            text="自动执行",
            font=("Microsoft YaHei UI", 16, "bold"),
            text_color=self.COLORS["text"],
        ).pack(side="left")
        self.mode_status = ctk.CTkLabel(
            control_header,
            text="当前：已停止",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["muted"],
        )
        self.mode_status.pack(side="right")

        button_row = ctk.CTkFrame(controls, fg_color="transparent")
        button_row.pack(fill="x", padx=18)
        button_specs = (
            (MODE_PRESS_F, "F6", "连续按 F", self.COLORS["blue"]),
            (MODE_CLICK, "F7", "连续点左键", self.COLORS["purple"]),
            (MODE_HOLD_W, "F8", "持续按住 W", self.COLORS["green"]),
        )
        for mode, hotkey, label, color in button_specs:
            button = ctk.CTkButton(
                button_row,
                text=f"{hotkey}\n{label}",
                height=66,
                corner_radius=13,
                fg_color=color,
                hover_color=self.COLORS["blue_hover"],
                text_color="#07111E" if mode == MODE_HOLD_W else "#FFFFFF",
                font=("Microsoft YaHei UI", 13, "bold"),
                command=lambda selected=mode: self._toggle_mode(selected),
            )
            button.pack(side="left", fill="x", expand=True, padx=5)
            self.mode_buttons[mode] = button
        self.stop_button = ctk.CTkButton(
            controls,
            text="F12   全部停止",
            height=40,
            corner_radius=12,
            fg_color="#30202A",
            hover_color="#4A2833",
            border_width=1,
            border_color="#6D3643",
            text_color=self.COLORS["red"],
            font=("Microsoft YaHei UI", 12, "bold"),
            command=self._stop,
        )
        self.stop_button.pack(fill="x", padx=23, pady=(12, 18))

        settings = ctk.CTkFrame(
            outer,
            corner_radius=18,
            fg_color=self.COLORS["card"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        settings.pack(fill="x", pady=(0, 12))
        settings_top = ctk.CTkFrame(settings, fg_color="transparent")
        settings_top.pack(fill="x", padx=22, pady=(16, 7))
        ctk.CTkLabel(
            settings_top,
            text="执行间隔",
            font=("Microsoft YaHei UI", 13, "bold"),
            text_color=self.COLORS["text"],
        ).pack(side="left")
        self.interval_value_label = ctk.CTkLabel(
            settings_top,
            text="120 ms",
            width=80,
            height=28,
            corner_radius=9,
            fg_color="#0C1626",
            text_color=self.COLORS["blue"],
            font=("Consolas", 12, "bold"),
        )
        self.interval_value_label.pack(side="right")
        self.interval_slider = ctk.CTkSlider(
            settings,
            from_=60,
            to=600,
            number_of_steps=54,
            variable=self.interval_value,
            progress_color=self.COLORS["blue"],
            button_color="#77A9FF",
            button_hover_color="#9BC0FF",
            command=self._apply_interval,
        )
        self.interval_slider.pack(fill="x", padx=24, pady=(2, 13))
        switch_row = ctk.CTkFrame(settings, fg_color="transparent")
        switch_row.pack(fill="x", padx=22, pady=(0, 16))
        ctk.CTkLabel(
            switch_row,
            text="只在原神位于前台时发送输入",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["text"],
        ).pack(side="left")
        self.game_switch = ctk.CTkSwitch(
            switch_row,
            text="推荐开启",
            variable=self.game_only,
            command=self._apply_game_only,
            progress_color=self.COLORS["green"],
            text_color=self.COLORS["muted"],
        )
        self.game_switch.pack(side="right")

        info = ctk.CTkFrame(outer, fg_color="#11243A", corner_radius=13)
        info.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            info,
            text="ⓘ  绿色“已就绪”表示已检测到原神且权限正确；切回游戏后即可使用快捷键。",
            font=("Microsoft YaHei UI", 11),
            text_color="#A9C9F4",
        ).pack(anchor="w", padx=16, pady=11)

        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.pack(fill="x")
        ctk.CTkButton(
            footer,
            text="最小化到托盘",
            width=150,
            height=36,
            corner_radius=10,
            fg_color="#1B2A40",
            hover_color="#253852",
            command=self._hide_to_tray,
        ).pack(side="left")
        ctk.CTkButton(
            footer,
            text="退出软件",
            width=110,
            height=36,
            corner_radius=10,
            fg_color="transparent",
            hover_color="#30202A",
            border_width=1,
            border_color="#4B3340",
            text_color=self.COLORS["red"],
            command=self.close,
        ).pack(side="right")

    def _setup_tray(self) -> None:
        if pystray is None or Image is None or ImageDraw is None:
            messagebox.showwarning(
                "缺少托盘组件",
                "当前以源码方式运行且缺少托盘组件。请使用打包后的 exe，或运行 build.ps1。",
            )
            return

        icon_image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        drawing = ImageDraw.Draw(icon_image)
        drawing.rounded_rectangle((4, 4, 60, 60), radius=15, fill=(54, 116, 224, 255))
        drawing.rectangle((20, 16, 45, 23), fill=(255, 255, 255, 255))
        drawing.rectangle((20, 16, 27, 49), fill=(255, 255, 255, 255))
        drawing.rectangle((20, 30, 40, 37), fill=(255, 255, 255, 255))

        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", lambda *_: self._call_on_ui(self._restore_window), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "F6  连按 F",
                lambda *_: self._call_on_ui(lambda: self._toggle_mode(MODE_PRESS_F)),
                checked=lambda _item: self.engine.snapshot()[0] == MODE_PRESS_F,
            ),
            pystray.MenuItem(
                "F7  连点左键",
                lambda *_: self._call_on_ui(lambda: self._toggle_mode(MODE_CLICK)),
                checked=lambda _item: self.engine.snapshot()[0] == MODE_CLICK,
            ),
            pystray.MenuItem(
                "F8  长按 W",
                lambda *_: self._call_on_ui(lambda: self._toggle_mode(MODE_HOLD_W)),
                checked=lambda _item: self.engine.snapshot()[0] == MODE_HOLD_W,
            ),
            pystray.MenuItem("F12  全部停止", lambda *_: self._call_on_ui(self._stop)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda *_: self._call_on_ui(self.close)),
        )
        self._tray_icon = pystray.Icon("genshin_story_helper", icon_image, APP_TITLE, menu)
        threading.Thread(target=self._tray_icon.run, name="tray-icon", daemon=True).start()

    def _call_on_ui(self, callback) -> None:
        if not self._closing:
            self.root.after(0, callback)

    def _on_window_unmap(self, _event=None) -> None:
        if not self._closing:
            self._unmap_after_id = self.root.after(50, self._hide_if_minimized)

    def _hide_if_minimized(self) -> None:
        if not self._closing and self.root.state() == "iconic":
            self._hide_to_tray()

    def _hide_to_tray(self) -> None:
        if self._closing:
            return
        if self._tray_icon is None:
            self.close()
            return
        self.root.withdraw()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            try:
                self._tray_icon.notify(
                    "软件仍在后台运行；双击托盘图标可恢复，F12 可随时停止。",
                    APP_TITLE,
                )
            except Exception:
                pass

    def _restore_window(self) -> None:
        if self._closing:
            return
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def _refresh_tray_menu(self) -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.update_menu()
            except Exception:
                pass

    def _apply_interval(self, raw_value=None) -> None:
        value = round(float(raw_value if raw_value is not None else self.interval_value.get()) / 10) * 10
        value = max(60, min(value, 600))
        self.interval_value.set(value)
        self.interval_value_label.configure(text=f"{value} ms")
        self.engine.set_interval_ms(value)

    def _apply_game_only(self) -> None:
        self.engine.set_game_only(self.game_only.get())

    def _toggle_mode(self, mode: str) -> None:
        self._apply_interval()
        self.engine.toggle(mode)
        self._update_mode_display()
        self._refresh_tray_menu()

    def _stop(self) -> None:
        self.engine.set_mode(None)
        send_key(VK_W, False)
        self._update_mode_display()
        self._refresh_tray_menu()

    def _poll_hotkeys(self) -> None:
        if self._closing:
            return
        try:
            while True:
                mode = self.hotkey_events.get_nowait()
                if mode is None:
                    self._stop()
                else:
                    self._toggle_mode(mode)
        except queue.Empty:
            pass
        if not self._closing:
            self._hotkey_after_id = self.root.after(50, self._poll_hotkeys)

    def _update_mode_display(self, game_active: bool | None = None) -> None:
        mode, _, game_only = self.engine.snapshot()
        if game_active is None:
            game_active = is_game_foreground()
        if mode is None:
            text = "当前：已停止"
            color = self.COLORS["muted"]
        elif game_only and not game_active:
            text = f"已选择：{MODE_NAMES[mode]} · 等待切回游戏"
            color = self.COLORS["amber"]
        else:
            text = f"正在执行：{MODE_NAMES[mode]}"
            color = self.COLORS["green"]
        self.mode_status.configure(text=text, text_color=color)

        for button_mode, button in self.mode_buttons.items():
            button.configure(
                border_width=2 if button_mode == mode else 0,
                border_color="#FFFFFF",
            )

    def _refresh_status(self) -> None:
        if self._closing:
            return
        game_processes = find_game_processes()
        game_running = bool(game_processes)
        game_active = is_game_foreground()
        elevated = is_elevated()
        ready = game_running and elevated

        if not game_running:
            self.connection_badge.configure(
                text="● 未检测到原神",
                text_color=self.COLORS["muted"],
            )
            self.connection_detail.configure(text="启动原神后，这里会自动变为绿色已就绪状态")
            self.process_detail.configure(text="GAME OFFLINE\nPID  —")
        elif not elevated:
            pid, process_name = game_processes[0]
            self.connection_badge.configure(
                text="● 权限不足，暂不可执行",
                text_color=self.COLORS["red"],
            )
            self.connection_detail.configure(text="请退出旧版，并以管理员身份启动新版助手")
            self.process_detail.configure(text=f"{process_name}\nPID  {pid}")
        elif game_active:
            pid, process_name = game_processes[0]
            self.connection_badge.configure(
                text="● 已就绪 · 可以执行",
                text_color=self.COLORS["green"],
            )
            self.connection_detail.configure(text="原神位于前台，全局快捷键和控制按钮已生效")
            self.process_detail.configure(text=f"{process_name}\nPID  {pid}")
        else:
            pid, process_name = game_processes[0]
            self.connection_badge.configure(
                text="● 原神已连接 · 可以执行",
                text_color=self.COLORS["green"],
            )
            self.connection_detail.configure(text="权限正确；切回原神窗口后自动开始输入")
            self.process_detail.configure(text=f"{process_name}\nPID  {pid}")

        if elevated:
            self.permission_badge.configure(
                text="✓ 权限正常",
                fg_color="#15372F",
                text_color=self.COLORS["green"],
            )
        else:
            self.permission_badge.configure(
                text="! 需要管理员权限",
                fg_color="#3A2229",
                text_color=self.COLORS["red"],
            )

        self._update_mode_display(game_active)

        if ready and self._last_ready is not True and self._tray_icon is not None:
            try:
                self._tray_icon.notify(
                    "已检测到原神，权限正常。切回游戏后即可使用 F6 / F7 / F8。",
                    "把你砌进神像里已就绪",
                )
            except Exception:
                pass
        self._last_ready = ready

        if self._tray_icon is not None:
            self._tray_icon.title = "把你砌进神像里 - " + (
                "已就绪" if ready else "等待原神"
            )

        if not self._closing:
            self._status_after_id = self.root.after(350, self._refresh_status)

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        for after_id in (
            self._hotkey_after_id,
            self._status_after_id,
            self._unmap_after_id,
            self._warning_after_id,
        ):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except (tk.TclError, ValueError):
                    pass
        self.engine.close()
        self.hotkeys.close()
        if self._tray_icon is not None:
            self._tray_icon.stop()
        self.root.destroy()

    # v4 presentation and reliable-input overrides. Genshin's Unity input layer
    # ignores posted keyboard messages while unfocused, so the UI no longer
    # claims that a window handle alone means background input is available.
    def _install_full_background(self) -> None:
        self.root.update_idletasks()
        width = max(1, self.root.winfo_width())
        height = max(1, self.root.winfo_height())
        artwork = Image.open(
            resource_path(os.path.join("assets", "raiden-sword-bg.png"))
        ).convert("RGBA")
        scale = max(width / artwork.width, height / artwork.height)
        resized = artwork.resize(
            (int(artwork.width * scale), int(artwork.height * scale)),
            Image.Resampling.LANCZOS,
        )
        left = max(0, (resized.width - width) // 2)
        top = max(0, (resized.height - height) // 2)
        resized = resized.crop((left, top, left + width, top + height))

        # Darken the left side for UI legibility while keeping the sword and
        # character clearly visible across the full window background.
        shade = Image.new("RGBA", (width, height), (4, 7, 20, 0))
        shade_drawing = ImageDraw.Draw(shade)
        for x in range(width):
            progress = x / max(1, width - 1)
            alpha = int(155 - 105 * progress)
            shade_drawing.line((x, 0, x, height), fill=(4, 7, 20, alpha))
        composed = Image.alpha_composite(resized, shade)
        self.background_image = ctk.CTkImage(
            light_image=composed,
            dark_image=composed,
            size=(width, height),
        )
        self.background_label = ctk.CTkLabel(
            self.root,
            text="",
            image=self.background_image,
        )
        self.background_label.place(x=0, y=0)

    def _build_ui(self) -> None:
        self._install_full_background()
        panel = ctk.CTkFrame(
            self.root,
            corner_radius=20,
            fg_color="#0B1020",
            border_width=1,
            border_color="#7058A8",
        )
        panel.place(relx=0.022, rely=0.035, relwidth=0.66, relheight=0.93)

        header = ctk.CTkFrame(panel, fg_color="transparent", height=58)
        header.pack(fill="x", padx=18, pady=(14, 4))
        header.pack_propagate(False)
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.pack(side="left")
        ctk.CTkLabel(
            title_group,
            text="把你砌进神像里",
            font=("Microsoft YaHei UI", 25, "bold"),
            text_color=self.COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="可靠前台输入 · 全局快捷键",
            font=("Microsoft YaHei UI", 13),
            text_color="#C7BBE8",
        ).pack(anchor="w")
        self.permission_badge = ctk.CTkLabel(
            header,
            text="检查中",
            width=112,
            height=34,
            corner_radius=17,
            fg_color="#2A2643",
            text_color=self.COLORS["muted"],
            font=("Microsoft YaHei UI", 13, "bold"),
        )
        self.permission_badge.pack(side="right", pady=4)

        status_card = ctk.CTkFrame(
            panel,
            height=88,
            corner_radius=15,
            fg_color="#171D31",
            border_width=1,
            border_color="#3B456B",
        )
        status_card.pack(fill="x", padx=16, pady=(4, 8))
        status_card.pack_propagate(False)
        status_text = ctk.CTkFrame(status_card, fg_color="transparent")
        status_text.pack(side="left", fill="both", expand=True, padx=15, pady=10)
        self.connection_badge = ctk.CTkLabel(
            status_text,
            text="● 正在检测原神",
            font=("Microsoft YaHei UI", 19, "bold"),
            text_color=self.COLORS["muted"],
        )
        self.connection_badge.pack(anchor="w")
        self.connection_detail = ctk.CTkLabel(
            status_text,
            text="请稍候…",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["muted"],
        )
        self.connection_detail.pack(anchor="w", pady=(3, 0))
        self.process_detail = ctk.CTkLabel(
            status_card,
            text="PID —",
            width=104,
            height=54,
            corner_radius=12,
            fg_color="#0D1324",
            text_color="#B9B4D3",
            font=("Consolas", 11),
        )
        self.process_detail.pack(side="right", padx=13)

        self.tabs = ctk.CTkTabview(
            panel,
            corner_radius=15,
            fg_color="#12182A",
            border_width=1,
            border_color="#3B456B",
            segmented_button_selected_color=self.COLORS["violet"],
            segmented_button_selected_hover_color=self.COLORS["violet_hover"],
            segmented_button_unselected_color="#282D49",
            text_color=self.COLORS["text"],
        )
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        control_tab = self.tabs.add("控制")
        settings_tab = self.tabs.add("按键设置")
        self._build_control_tab(control_tab)
        self._build_settings_tab(settings_tab)

        footer = ctk.CTkFrame(panel, fg_color="transparent", height=42)
        footer.pack(fill="x", padx=16, pady=(0, 12))
        footer.pack_propagate(False)
        ctk.CTkButton(
            footer,
            text="收进托盘",
            width=118,
            height=36,
            corner_radius=11,
            fg_color="#2B3150",
            hover_color="#3A456B",
            font=("Microsoft YaHei UI", 13, "bold"),
            command=self._hide_to_tray,
        ).pack(side="left")
        self.mode_status = ctk.CTkLabel(
            footer,
            text="已停止",
            font=("Microsoft YaHei UI", 14, "bold"),
            text_color=self.COLORS["muted"],
        )
        self.mode_status.pack(side="left", padx=15)
        ctk.CTkButton(
            footer,
            text="退出",
            width=80,
            height=36,
            corner_radius=11,
            fg_color="#38212D",
            hover_color="#512C3C",
            text_color=self.COLORS["red"],
            font=("Microsoft YaHei UI", 13, "bold"),
            command=self.close,
        ).pack(side="right")

    def _build_control_tab(self, parent) -> None:
        mode_row = ctk.CTkFrame(parent, fg_color="transparent")
        mode_row.pack(fill="x", padx=8, pady=(13, 9))
        for mode, color in (
            (MODE_PRESS_F, self.COLORS["violet"]),
            (MODE_CLICK, self.COLORS["pink"]),
            (MODE_HOLD_W, self.COLORS["blue"]),
        ):
            button = ctk.CTkButton(
                mode_row,
                text="",
                height=74,
                corner_radius=14,
                fg_color=color,
                hover_color=self.COLORS["violet_hover"],
                text_color="#FFFFFF",
                font=("Microsoft YaHei UI", 17, "bold"),
                command=lambda selected=mode: self._toggle_mode(selected),
            )
            button.pack(side="left", fill="x", expand=True, padx=5)
            self.mode_buttons[mode] = button
        self._refresh_button_texts()

        self.stop_button = ctk.CTkButton(
            parent,
            text=f"急停   {self.settings['hotkeys']['stop']}",
            height=46,
            corner_radius=12,
            fg_color="#3A2230",
            hover_color="#542E42",
            border_width=1,
            border_color="#8A4860",
            text_color=self.COLORS["red"],
            font=("Microsoft YaHei UI", 16, "bold"),
            command=self._stop,
        )
        self.stop_button.pack(fill="x", padx=13, pady=(0, 11))

        interval_header = ctk.CTkFrame(parent, fg_color="transparent")
        interval_header.pack(fill="x", padx=15)
        ctk.CTkLabel(
            interval_header,
            text="执行间隔",
            font=("Microsoft YaHei UI", 15, "bold"),
            text_color=self.COLORS["text"],
        ).pack(side="left")
        self.interval_value_label = ctk.CTkLabel(
            interval_header,
            text=f"{int(self.interval_value.get())} ms",
            width=78,
            height=28,
            corner_radius=9,
            fg_color="#0D1324",
            text_color=self.COLORS["pink"],
            font=("Consolas", 12, "bold"),
        )
        self.interval_value_label.pack(side="right")
        ctk.CTkSlider(
            parent,
            from_=60,
            to=600,
            number_of_steps=54,
            variable=self.interval_value,
            progress_color=self.COLORS["violet"],
            button_color=self.COLORS["pink"],
            button_hover_color="#FFD0F0",
            command=self._apply_interval,
        ).pack(fill="x", padx=18, pady=(6, 11))

        focus_card = ctk.CTkFrame(parent, fg_color="#211D3B", corner_radius=13)
        focus_card.pack(fill="x", padx=12, pady=(0, 7))
        focus_text = ctk.CTkFrame(focus_card, fg_color="transparent")
        focus_text.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        ctk.CTkLabel(
            focus_text,
            text="启动功能时自动切换到原神",
            font=("Microsoft YaHei UI", 15, "bold"),
            text_color=self.COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            focus_text,
            text="确保角色移动和剧情按键真正生效",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["muted"],
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkSwitch(
            focus_card,
            text="",
            width=50,
            variable=self.auto_focus,
            progress_color=self.COLORS["green"],
            command=self._apply_auto_focus,
        ).pack(side="right", padx=14)

        ctk.CTkLabel(
            parent,
            text="原神拒绝失焦键盘消息：角色移动时必须让原神获得输入焦点。看视频可使用浏览器画中画置顶。",
            wraplength=610,
            justify="left",
            font=("Microsoft YaHei UI", 12),
            text_color="#D1C7ED",
        ).pack(anchor="w", padx=15, pady=(2, 0))

    def _build_settings_tab(self, parent) -> None:
        action_row = ctk.CTkFrame(parent, fg_color="#202640", corner_radius=13)
        action_row.pack(fill="x", padx=12, pady=(13, 9))
        for index, (key, label, value) in enumerate((
            ("press_key", "连按动作键", str(self.settings["press_key"])),
            ("hold_key", "长按动作键", str(self.settings["hold_key"])),
        )):
            cell = ctk.CTkFrame(action_row, fg_color="transparent")
            cell.grid(row=0, column=index, sticky="ew", padx=11, pady=11)
            action_row.grid_columnconfigure(index, weight=1)
            ctk.CTkLabel(
                cell,
                text=label,
                font=("Microsoft YaHei UI", 14, "bold"),
                text_color=self.COLORS["muted"],
            ).pack(anchor="w")
            entry = ctk.CTkEntry(
                cell,
                height=42,
                corner_radius=10,
                fg_color="#0D1324",
                border_color="#4B557B",
                text_color=self.COLORS["text"],
                font=("Consolas", 16, "bold"),
            )
            entry.pack(fill="x", pady=(5, 0))
            entry.insert(0, value)
            self.action_entries[key] = entry

        hotkey_card = ctk.CTkFrame(parent, fg_color="transparent")
        hotkey_card.pack(fill="x", padx=14)
        labels = {
            "press": "切换连按",
            "click": "切换左键",
            "hold": "切换长按",
            "stop": "全部急停",
        }
        for row, key in enumerate(("press", "click", "hold", "stop")):
            ctk.CTkLabel(
                hotkey_card,
                text=labels[key],
                width=104,
                anchor="w",
                font=("Microsoft YaHei UI", 14, "bold"),
                text_color=self.COLORS["text"],
            ).grid(row=row, column=0, sticky="w", pady=5)
            entry = ctk.CTkEntry(
                hotkey_card,
                height=39,
                corner_radius=10,
                fg_color="#0D1324",
                border_color="#4B557B",
                text_color=self.COLORS["pink"],
                font=("Consolas", 14, "bold"),
                placeholder_text="例如 Ctrl+Alt+K",
            )
            entry.grid(row=row, column=1, sticky="ew", padx=(9, 0), pady=5)
            entry.insert(0, str(self.settings["hotkeys"][key]))
            hotkey_card.grid_columnconfigure(1, weight=1)
            self.hotkey_entries[key] = entry

        apply_row = ctk.CTkFrame(parent, fg_color="transparent")
        apply_row.pack(fill="x", padx=14, pady=(10, 0))
        self.setting_feedback = ctk.CTkLabel(
            apply_row,
            text="支持 Ctrl / Alt / Shift / Win 组合键",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["muted"],
        )
        self.setting_feedback.pack(side="left")
        ctk.CTkButton(
            apply_row,
            text="应用并保存",
            width=132,
            height=40,
            corner_radius=11,
            fg_color=self.COLORS["violet"],
            hover_color=self.COLORS["violet_hover"],
            font=("Microsoft YaHei UI", 14, "bold"),
            command=self._apply_key_settings,
        ).pack(side="right")

    def _apply_auto_focus(self) -> None:
        self.settings["auto_focus"] = bool(self.auto_focus.get())
        save_settings(self.settings)

    def _toggle_mode(self, mode: str) -> None:
        selected_mode = self.engine.toggle(mode)
        if selected_mode is not None and self.auto_focus.get():
            activate_game_window()
        self._update_mode_display()
        self._refresh_tray_menu()

    def _update_mode_display(self, game_active: bool | None = None, game_window: int | None = None) -> None:
        mode = self.engine.snapshot()[0]
        if game_active is None:
            game_active = is_game_foreground()
        if mode is None:
            text, color = "已停止", self.COLORS["muted"]
        elif game_active:
            text, color = "正在执行：" + self._mode_name(mode), self.COLORS["green"]
        else:
            text, color = "已暂停，等待原神获得焦点", self.COLORS["amber"]
        self.mode_status.configure(text=text, text_color=color)
        for button_mode, button in self.mode_buttons.items():
            button.configure(
                border_width=2 if button_mode == mode else 0,
                border_color="#FFFFFF",
            )

    def _refresh_status(self) -> None:
        if self._closing:
            return
        processes = find_game_processes()
        game_running = bool(processes)
        game_active = is_game_foreground()
        elevated = is_elevated()
        ready = bool(game_running and game_active and elevated)

        if not game_running:
            badge, detail, color, process_text = (
                "● 未检测到原神",
                "请先启动游戏",
                self.COLORS["muted"],
                "PID —",
            )
        elif not elevated:
            pid, process_name = processes[0]
            badge, detail, color, process_text = (
                "● 权限不足",
                "请以管理员身份启动助手",
                self.COLORS["red"],
                f"{process_name}\n{pid}",
            )
        elif game_active:
            pid, process_name = processes[0]
            badge, detail, color, process_text = (
                "● 原神已激活 · 输入可执行",
                "角色移动与剧情按键会正常发送",
                self.COLORS["green"],
                f"{process_name}\n{pid}",
            )
        else:
            pid, process_name = processes[0]
            badge, detail, color, process_text = (
                "● 已检测到原神 · 尚未激活",
                "启动任一功能后会自动切换到原神",
                self.COLORS["amber"],
                f"{process_name}\n{pid}",
            )

        self.connection_badge.configure(text=badge, text_color=color)
        self.connection_detail.configure(text=detail)
        self.process_detail.configure(text=process_text)
        self.permission_badge.configure(
            text="✓ 权限正常" if elevated else "! 权限不足",
            fg_color="#173B35" if elevated else "#40232D",
            text_color=self.COLORS["green"] if elevated else self.COLORS["red"],
        )
        self._update_mode_display(game_active)
        if ready and self._last_ready is not True and self._tray_icon is not None:
            try:
                self._tray_icon.notify(
                    "原神已获得输入焦点，自动按键可以执行。",
                    "把你砌进神像里已就绪",
                )
            except Exception:
                pass
        self._last_ready = ready
        if self._tray_icon is not None:
            self._tray_icon.title = "把你砌进神像里 - " + ("可执行" if ready else "等待原神")
        self._status_after_id = self.root.after(350, self._refresh_status)


class StoryHelperApp:
    COLORS = {
        "window": "#0B1020",
        "card": "#151B2E",
        "card_alt": "#1C2440",
        "border": "#313A5D",
        "text": "#FFF8FF",
        "muted": "#A8A9C7",
        "violet": "#9B7BFF",
        "violet_hover": "#8263E6",
        "pink": "#F09BD8",
        "green": "#55D6A8",
        "amber": "#F6C85F",
        "red": "#FF727D",
        "blue": "#6BA7FF",
    }

    def __init__(self, root) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("540x540")
        self.root.resizable(False, False)
        self.root.configure(fg_color=self.COLORS["window"])
        self.window_icon = None
        try:
            self.window_icon = tk.PhotoImage(
                file=resource_path(os.path.join("assets", "raiden-app-icon-256.png"))
            )
            self.root.iconphoto(True, self.window_icon)
        except (OSError, tk.TclError):
            self.window_icon = None
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.root.bind("<Unmap>", self._on_window_unmap)

        self._closing = False
        self._tray_notice_shown = False
        self._tray_icon = None
        self._last_ready: bool | None = None
        self._hotkey_after_id = None
        self._status_after_id = None
        self._unmap_after_id = None
        self._warning_after_id = None

        self.settings = load_settings()
        # Genshin ignores synthetic keyboard window messages while unfocused.
        # Keep the reliable SendInput path and explicitly activate the game.
        self.settings["background_mode"] = False
        try:
            press_vk = key_name_to_vk(str(self.settings["press_key"]))
            hold_vk = key_name_to_vk(str(self.settings["hold_key"]))
        except ValueError:
            self.settings["press_key"] = "F"
            self.settings["hold_key"] = "W"
            press_vk, hold_vk = VK_F, VK_W

        self.engine = AutomationEngine(
            int(self.settings["interval_ms"]),
            bool(self.settings["background_mode"]),
            press_vk,
            hold_vk,
        )
        self.hotkey_events: queue.Queue[str | None] = queue.Queue()
        self.hotkeys = HotkeyListener(self.hotkey_events, self.settings["hotkeys"])

        self.interval_value = tk.DoubleVar(value=int(self.settings["interval_ms"]))
        self.background_mode = tk.BooleanVar(value=bool(self.settings["background_mode"]))
        self.auto_focus = tk.BooleanVar(value=bool(self.settings.get("auto_focus", True)))
        self.mode_buttons: dict[str, object] = {}
        self.hotkey_entries: dict[str, object] = {}
        self.action_entries: dict[str, object] = {}
        self.character_image = None

        self._build_ui()
        self._setup_tray()
        self._hotkey_after_id = self.root.after(50, self._poll_hotkeys)
        self._status_after_id = self.root.after(200, self._refresh_status)

        if self.hotkeys.error:
            self.setting_feedback.configure(
                text="部分快捷键未注册：" + self.hotkeys.error,
                text_color=self.COLORS["red"],
            )

    def _build_ui(self) -> None:
        outer = ctk.CTkFrame(self.root, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=18, pady=16)

        content = ctk.CTkFrame(outer, fg_color="transparent", width=510)
        content.pack(side="left", fill="both", expand=True, padx=(0, 14))

        header = ctk.CTkFrame(content, fg_color="transparent", height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.pack(side="left")
        ctk.CTkLabel(
            title_group,
            text="把你砌进神像里",
            font=("Microsoft YaHei UI", 21, "bold"),
            text_color=self.COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="可前台 / 后台定向执行",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["muted"],
        ).pack(anchor="w")
        self.permission_badge = ctk.CTkLabel(
            header,
            text="检查中",
            width=104,
            height=30,
            corner_radius=15,
            fg_color="#282D48",
            text_color=self.COLORS["muted"],
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        self.permission_badge.pack(side="right", pady=4)

        status_card = ctk.CTkFrame(
            content,
            height=82,
            corner_radius=16,
            fg_color=self.COLORS["card_alt"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        status_card.pack(fill="x", pady=(10, 8))
        status_card.pack_propagate(False)
        status_text = ctk.CTkFrame(status_card, fg_color="transparent")
        status_text.pack(side="left", fill="both", expand=True, padx=16, pady=10)
        self.connection_badge = ctk.CTkLabel(
            status_text,
            text="● 正在检测原神",
            font=("Microsoft YaHei UI", 17, "bold"),
            text_color=self.COLORS["muted"],
        )
        self.connection_badge.pack(anchor="w")
        self.connection_detail = ctk.CTkLabel(
            status_text,
            text="请稍候…",
            font=("Microsoft YaHei UI", 11),
            text_color=self.COLORS["muted"],
        )
        self.connection_detail.pack(anchor="w", pady=(3, 0))
        self.process_detail = ctk.CTkLabel(
            status_card,
            text="PID —",
            width=96,
            height=48,
            corner_radius=12,
            fg_color="#10162A",
            text_color=self.COLORS["muted"],
            font=("Consolas", 10),
        )
        self.process_detail.pack(side="right", padx=13)

        self.tabs = ctk.CTkTabview(
            content,
            height=394,
            corner_radius=16,
            fg_color=self.COLORS["card"],
            border_width=1,
            border_color=self.COLORS["border"],
            segmented_button_selected_color=self.COLORS["violet"],
            segmented_button_selected_hover_color=self.COLORS["violet_hover"],
            segmented_button_unselected_color="#242B48",
            text_color=self.COLORS["text"],
        )
        self.tabs.pack(fill="both", expand=True)
        control_tab = self.tabs.add("控制")
        settings_tab = self.tabs.add("按键设置")
        self._build_control_tab(control_tab)
        self._build_settings_tab(settings_tab)

        footer = ctk.CTkFrame(content, fg_color="transparent", height=38)
        footer.pack(fill="x", pady=(8, 0))
        footer.pack_propagate(False)
        ctk.CTkButton(
            footer,
            text="收进托盘",
            width=110,
            height=32,
            corner_radius=10,
            fg_color="#262D49",
            hover_color="#333C60",
            font=("Microsoft YaHei UI", 12, "bold"),
            command=self._hide_to_tray,
        ).pack(side="left")
        self.mode_status = ctk.CTkLabel(
            footer,
            text="已停止",
            font=("Microsoft YaHei UI", 12, "bold"),
            text_color=self.COLORS["muted"],
        )
        self.mode_status.pack(side="left", padx=14)
        ctk.CTkButton(
            footer,
            text="退出",
            width=76,
            height=32,
            corner_radius=10,
            fg_color="transparent",
            border_width=1,
            border_color="#573746",
            hover_color="#3A2532",
            text_color=self.COLORS["red"],
            command=self.close,
        ).pack(side="right")

        self._build_character_panel(outer)

    def _build_control_tab(self, parent) -> None:
        mode_row = ctk.CTkFrame(parent, fg_color="transparent")
        mode_row.pack(fill="x", padx=9, pady=(12, 8))
        mode_specs = (
            (MODE_PRESS_F, self.COLORS["violet"]),
            (MODE_CLICK, self.COLORS["pink"]),
            (MODE_HOLD_W, self.COLORS["blue"]),
        )
        for mode, color in mode_specs:
            button = ctk.CTkButton(
                mode_row,
                text="",
                height=58,
                corner_radius=13,
                fg_color=color,
                hover_color=self.COLORS["violet_hover"],
                text_color="#FFFFFF",
                font=("Microsoft YaHei UI", 14, "bold"),
                command=lambda selected=mode: self._toggle_mode(selected),
            )
            button.pack(side="left", fill="x", expand=True, padx=4)
            self.mode_buttons[mode] = button
        self._refresh_button_texts()

        self.stop_button = ctk.CTkButton(
            parent,
            text="",
            height=38,
            corner_radius=11,
            fg_color="#352330",
            hover_color="#4C2D3D",
            border_width=1,
            border_color="#7B4056",
            text_color=self.COLORS["red"],
            font=("Microsoft YaHei UI", 13, "bold"),
            command=self._stop,
        )
        self.stop_button.pack(fill="x", padx=13, pady=(0, 10))
        self.stop_button.configure(text=f"急停   {self.settings['hotkeys']['stop']}")

        interval_header = ctk.CTkFrame(parent, fg_color="transparent")
        interval_header.pack(fill="x", padx=14)
        ctk.CTkLabel(
            interval_header,
            text="执行间隔",
            font=("Microsoft YaHei UI", 13, "bold"),
            text_color=self.COLORS["text"],
        ).pack(side="left")
        self.interval_value_label = ctk.CTkLabel(
            interval_header,
            text=f"{int(self.interval_value.get())} ms",
            width=70,
            height=26,
            corner_radius=8,
            fg_color="#10162A",
            text_color=self.COLORS["pink"],
            font=("Consolas", 11, "bold"),
        )
        self.interval_value_label.pack(side="right")
        ctk.CTkSlider(
            parent,
            from_=60,
            to=600,
            number_of_steps=54,
            variable=self.interval_value,
            progress_color=self.COLORS["violet"],
            button_color=self.COLORS["pink"],
            button_hover_color="#FFD0F0",
            command=self._apply_interval,
        ).pack(fill="x", padx=17, pady=(5, 10))

        background_card = ctk.CTkFrame(parent, fg_color="#201D3A", corner_radius=12)
        background_card.pack(fill="x", padx=12, pady=(0, 8))
        background_text = ctk.CTkFrame(background_card, fg_color="transparent")
        background_text.pack(side="left", fill="both", expand=True, padx=13, pady=9)
        ctk.CTkLabel(
            background_text,
            text="后台定向输入",
            font=("Microsoft YaHei UI", 13, "bold"),
            text_color=self.COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            background_text,
            text="看视频或使用其他程序时，仍向原神窗口发送",
            font=("Microsoft YaHei UI", 10),
            text_color=self.COLORS["muted"],
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkSwitch(
            background_card,
            text="",
            width=48,
            variable=self.background_mode,
            progress_color=self.COLORS["green"],
            command=self._apply_background_mode,
        ).pack(side="right", padx=13)

        ctk.CTkLabel(
            parent,
            text="后台模式不会抢占焦点或移动当前鼠标；若游戏版本不接收失焦消息，可关闭此开关使用前台兼容模式。",
            wraplength=455,
            justify="left",
            font=("Microsoft YaHei UI", 10),
            text_color=self.COLORS["muted"],
        ).pack(anchor="w", padx=15, pady=(1, 0))

    def _build_settings_tab(self, parent) -> None:
        action_row = ctk.CTkFrame(parent, fg_color="#1D2540", corner_radius=12)
        action_row.pack(fill="x", padx=12, pady=(12, 8))
        for index, (key, label, value) in enumerate((
            ("press_key", "连按动作键", str(self.settings["press_key"])),
            ("hold_key", "长按动作键", str(self.settings["hold_key"])),
        )):
            cell = ctk.CTkFrame(action_row, fg_color="transparent")
            cell.grid(row=0, column=index, sticky="ew", padx=10, pady=10)
            action_row.grid_columnconfigure(index, weight=1)
            ctk.CTkLabel(
                cell,
                text=label,
                font=("Microsoft YaHei UI", 11, "bold"),
                text_color=self.COLORS["muted"],
            ).pack(anchor="w")
            entry = ctk.CTkEntry(
                cell,
                height=34,
                corner_radius=9,
                fg_color="#10162A",
                border_color=self.COLORS["border"],
                text_color=self.COLORS["text"],
                font=("Consolas", 14, "bold"),
            )
            entry.pack(fill="x", pady=(4, 0))
            entry.insert(0, value)
            self.action_entries[key] = entry

        hotkey_card = ctk.CTkFrame(parent, fg_color="transparent")
        hotkey_card.pack(fill="x", padx=13)
        labels = {
            "press": "切换连按",
            "click": "切换左键",
            "hold": "切换长按",
            "stop": "全部急停",
        }
        for row, key in enumerate(("press", "click", "hold", "stop")):
            ctk.CTkLabel(
                hotkey_card,
                text=labels[key],
                width=92,
                anchor="w",
                font=("Microsoft YaHei UI", 14, "bold"),
                text_color=self.COLORS["text"],
            ).grid(row=row, column=0, sticky="w", pady=4)
            entry = ctk.CTkEntry(
                hotkey_card,
                height=32,
                corner_radius=9,
                fg_color="#10162A",
                border_color=self.COLORS["border"],
                text_color=self.COLORS["pink"],
                font=("Consolas", 12, "bold"),
                placeholder_text="例如 Ctrl+Alt+K",
            )
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)
            entry.insert(0, str(self.settings["hotkeys"][key]))
            hotkey_card.grid_columnconfigure(1, weight=1)
            self.hotkey_entries[key] = entry

        apply_row = ctk.CTkFrame(parent, fg_color="transparent")
        apply_row.pack(fill="x", padx=13, pady=(9, 0))
        self.setting_feedback = ctk.CTkLabel(
            apply_row,
            text="支持 Ctrl / Alt / Shift / Win 组合键",
            font=("Microsoft YaHei UI", 10),
            text_color=self.COLORS["muted"],
        )
        self.setting_feedback.pack(side="left")
        ctk.CTkButton(
            apply_row,
            text="应用并保存",
            width=118,
            height=34,
            corner_radius=10,
            fg_color=self.COLORS["violet"],
            hover_color=self.COLORS["violet_hover"],
            font=("Microsoft YaHei UI", 12, "bold"),
            command=self._apply_key_settings,
        ).pack(side="right")

    def _build_character_panel(self, parent) -> None:
        panel = ctk.CTkFrame(
            parent,
            width=196,
            corner_radius=18,
            fg_color="#211A38",
            border_width=1,
            border_color="#59468A",
        )
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)
        try:
            artwork = Image.open(resource_path(os.path.join("assets", "raiden-sidebar.png"))).convert("RGB")
            target_ratio = 196 / 868
            crop_width = int(artwork.height * target_ratio)
            left = max(0, min(artwork.width - crop_width, int(artwork.width * 0.38)))
            artwork = artwork.crop((left, 0, left + crop_width, artwork.height))
            self.character_image = ctk.CTkImage(
                light_image=artwork,
                dark_image=artwork,
                size=(196, 868),
            )
            ctk.CTkLabel(panel, text="", image=self.character_image).place(x=0, y=0)
        except (OSError, ValueError):
            ctk.CTkLabel(
                panel,
                text="雷\n电\n将\n军",
                font=("Microsoft YaHei UI", 23, "bold"),
                text_color=self.COLORS["violet"],
            ).place(relx=0.5, rely=0.42, anchor="center")
        ctk.CTkLabel(
            panel,
            text="⚡  御建鸣神主尊",
            width=164,
            height=32,
            corner_radius=13,
            fg_color="#241C3D",
            text_color="#E8DAFF",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).place(relx=0.5, rely=0.95, anchor="center")

    def _setup_tray(self) -> None:
        if pystray is None or Image is None or ImageDraw is None:
            return
        try:
            artwork = Image.open(resource_path(os.path.join("assets", "raiden-sidebar.png"))).convert("RGBA")
            side = min(artwork.width, artwork.height)
            left = max(0, min(artwork.width - side, artwork.width // 2 - side // 2))
            icon_image = artwork.crop((left, 0, left + side, side)).resize((64, 64))
        except OSError:
            icon_image = Image.new("RGBA", (64, 64), (33, 26, 56, 255))
            drawing = ImageDraw.Draw(icon_image)
            drawing.ellipse((10, 10, 54, 54), fill=(155, 123, 255, 255))

        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", lambda *_: self._call_on_ui(self._restore_window), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "连按设定键",
                lambda *_: self._call_on_ui(lambda: self._toggle_mode(MODE_PRESS_F)),
                checked=lambda _item: self.engine.snapshot()[0] == MODE_PRESS_F,
            ),
            pystray.MenuItem(
                "连续点左键",
                lambda *_: self._call_on_ui(lambda: self._toggle_mode(MODE_CLICK)),
                checked=lambda _item: self.engine.snapshot()[0] == MODE_CLICK,
            ),
            pystray.MenuItem(
                "长按设定键",
                lambda *_: self._call_on_ui(lambda: self._toggle_mode(MODE_HOLD_W)),
                checked=lambda _item: self.engine.snapshot()[0] == MODE_HOLD_W,
            ),
            pystray.MenuItem("全部停止", lambda *_: self._call_on_ui(self._stop)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda *_: self._call_on_ui(self.close)),
        )
        self._tray_icon = pystray.Icon("genshin_story_helper", icon_image, APP_TITLE, menu)
        threading.Thread(target=self._tray_icon.run, name="tray-icon", daemon=True).start()

    def _mode_name(self, mode: str | None) -> str:
        if mode == MODE_PRESS_F:
            return f"连按 {self.settings['press_key']}"
        if mode == MODE_CLICK:
            return "连续点左键"
        if mode == MODE_HOLD_W:
            return f"长按 {self.settings['hold_key']}"
        return "已停止"

    def _refresh_button_texts(self) -> None:
        if not self.mode_buttons:
            return
        hotkeys = self.settings["hotkeys"]
        self.mode_buttons[MODE_PRESS_F].configure(
            text=f"{hotkeys['press']}\n连按 {self.settings['press_key']}"
        )
        self.mode_buttons[MODE_CLICK].configure(
            text=f"{hotkeys['click']}\n连续点左键"
        )
        self.mode_buttons[MODE_HOLD_W].configure(
            text=f"{hotkeys['hold']}\n长按 {self.settings['hold_key']}"
        )
        if hasattr(self, "stop_button"):
            self.stop_button.configure(text=f"急停   {hotkeys['stop']}")

    def _apply_key_settings(self) -> None:
        try:
            press_name = self.action_entries["press_key"].get().strip().upper()
            hold_name = self.action_entries["hold_key"].get().strip().upper()
            press_vk = key_name_to_vk(press_name)
            hold_vk = key_name_to_vk(hold_name)
            bindings = {
                key: entry.get().strip()
                for key, entry in self.hotkey_entries.items()
            }
            parsed = [parse_hotkey(bindings[key]) for key in ("press", "click", "hold", "stop")]
            if len(set(parsed)) != len(parsed):
                raise ValueError("四个快捷键不能重复")
        except ValueError as error:
            self.setting_feedback.configure(text=str(error), text_color=self.COLORS["red"])
            return

        self.engine.set_action_keys(press_vk, hold_vk)
        self.hotkeys.close()
        self.hotkeys = HotkeyListener(self.hotkey_events, bindings)
        self.settings["press_key"] = press_name
        self.settings["hold_key"] = hold_name
        self.settings["hotkeys"] = bindings
        save_settings(self.settings)
        self._refresh_button_texts()
        self._refresh_tray_menu()
        if self.hotkeys.error:
            self.setting_feedback.configure(
                text=self.hotkeys.error,
                text_color=self.COLORS["red"],
            )
        else:
            self.setting_feedback.configure(
                text="✓ 新按键已保存并立即生效",
                text_color=self.COLORS["green"],
            )

    def _apply_interval(self, raw_value=None) -> None:
        value = round(float(raw_value if raw_value is not None else self.interval_value.get()) / 10) * 10
        value = max(60, min(value, 600))
        self.interval_value.set(value)
        self.interval_value_label.configure(text=f"{value} ms")
        self.settings["interval_ms"] = value
        self.engine.set_interval_ms(value)

    def _apply_background_mode(self) -> None:
        enabled = bool(self.background_mode.get())
        self.settings["background_mode"] = enabled
        self.engine.stop()
        self.engine.set_background_mode(enabled)
        save_settings(self.settings)
        self._update_mode_display()

    def _toggle_mode(self, mode: str) -> None:
        self.engine.toggle(mode)
        self._update_mode_display()
        self._refresh_tray_menu()

    def _stop(self) -> None:
        self.engine.stop()
        self._update_mode_display()
        self._refresh_tray_menu()

    def _update_mode_display(self, game_active: bool | None = None, game_window: int | None = None) -> None:
        mode, _, background_mode, _, _ = self.engine.snapshot()
        if game_active is None:
            game_active = is_game_foreground()
        if game_window is None:
            game_window = find_game_window()
        if mode is None:
            text, color = "已停止", self.COLORS["muted"]
        elif background_mode and game_window:
            text, color = "后台执行：" + self._mode_name(mode), self.COLORS["green"]
        elif not background_mode and game_active:
            text, color = "前台执行：" + self._mode_name(mode), self.COLORS["green"]
        else:
            text, color = "等待原神：" + self._mode_name(mode), self.COLORS["amber"]
        self.mode_status.configure(text=text, text_color=color)
        for button_mode, button in self.mode_buttons.items():
            button.configure(
                border_width=2 if button_mode == mode else 0,
                border_color="#FFFFFF",
            )

    def _refresh_status(self) -> None:
        if self._closing:
            return
        processes = find_game_processes()
        game_running = bool(processes)
        game_window = find_game_window()
        game_active = is_game_foreground()
        elevated = is_elevated()
        background_mode = bool(self.engine.snapshot()[2])
        ready = bool(game_running and elevated and (game_window if background_mode else game_active))

        if not game_running:
            badge = "● 未检测到原神"
            detail = "启动游戏后会自动连接"
            color = self.COLORS["muted"]
            process_text = "PID —"
        elif not elevated:
            pid, process_name = processes[0]
            badge = "● 权限不足"
            detail = "请以管理员身份启动助手"
            color = self.COLORS["red"]
            process_text = f"{process_name}\n{pid}"
        elif background_mode and game_window:
            pid, process_name = processes[0]
            badge = "● 后台已连接 · 可执行"
            detail = "原神可在后台，输入不会抢占当前焦点"
            color = self.COLORS["green"]
            process_text = f"{process_name}\n{pid}"
        elif not background_mode and game_active:
            pid, process_name = processes[0]
            badge = "● 前台已就绪 · 可执行"
            detail = "当前使用前台兼容输入模式"
            color = self.COLORS["green"]
            process_text = f"{process_name}\n{pid}"
        else:
            pid, process_name = processes[0]
            badge = "● 已发现原神 · 等待窗口"
            detail = "切回原神，或开启后台定向输入"
            color = self.COLORS["amber"]
            process_text = f"{process_name}\n{pid}"

        self.connection_badge.configure(text=badge, text_color=color)
        self.connection_detail.configure(text=detail)
        self.process_detail.configure(text=process_text)
        self.permission_badge.configure(
            text="✓ 权限正常" if elevated else "! 权限不足",
            fg_color="#173B35" if elevated else "#40232D",
            text_color=self.COLORS["green"] if elevated else self.COLORS["red"],
        )
        self._update_mode_display(game_active, game_window)

        if ready and self._last_ready is not True and self._tray_icon is not None:
            try:
                mode_text = "后台窗口" if background_mode else "前台窗口"
                self._tray_icon.notify(
                    f"原神{mode_text}已经连接，可以执行自动输入。",
                    "把你砌进神像里已就绪",
                )
            except Exception:
                pass
        self._last_ready = ready
        if self._tray_icon is not None:
            self._tray_icon.title = "把你砌进神像里 - " + ("已就绪" if ready else "等待原神")
        self._status_after_id = self.root.after(400, self._refresh_status)

    def _poll_hotkeys(self) -> None:
        if self._closing:
            return
        try:
            while True:
                mode = self.hotkey_events.get_nowait()
                self._stop() if mode is None else self._toggle_mode(mode)
        except queue.Empty:
            pass
        self._hotkey_after_id = self.root.after(50, self._poll_hotkeys)

    def _refresh_tray_menu(self) -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.update_menu()
            except Exception:
                pass

    def _call_on_ui(self, callback) -> None:
        if not self._closing:
            self.root.after(0, callback)

    def _on_window_unmap(self, _event=None) -> None:
        if not self._closing:
            self._unmap_after_id = self.root.after(50, self._hide_if_minimized)

    def _hide_if_minimized(self) -> None:
        if not self._closing and self.root.state() == "iconic":
            self._hide_to_tray()

    def _hide_to_tray(self) -> None:
        if self._closing:
            return
        if self._tray_icon is None:
            self.close()
            return
        self.root.withdraw()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            try:
                self._tray_icon.notify(
                    "助手仍在后台运行；双击雷电将军头像可恢复窗口。",
                    "把你砌进神像里",
                )
            except Exception:
                pass

    def _restore_window(self) -> None:
        if self._closing:
            return
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.settings["interval_ms"] = int(self.interval_value.get())
        save_settings(self.settings)
        for after_id in (
            self._hotkey_after_id,
            self._status_after_id,
            self._unmap_after_id,
            self._warning_after_id,
        ):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except (tk.TclError, ValueError):
                    pass
        self.engine.close()
        self.hotkeys.close()
        if self._tray_icon is not None:
            self._tray_icon.stop()
        self.root.destroy()

    # Bind the v4 full-background presentation and reliable focus behavior.
    _install_full_background = LegacyStoryHelperApp._install_full_background
    _build_ui = LegacyStoryHelperApp._build_ui
    _build_control_tab = LegacyStoryHelperApp._build_control_tab
    _build_settings_tab = LegacyStoryHelperApp._build_settings_tab
    _apply_auto_focus = LegacyStoryHelperApp._apply_auto_focus
    _toggle_mode = LegacyStoryHelperApp._toggle_mode
    _update_mode_display = LegacyStoryHelperApp._update_mode_display
    _refresh_status = LegacyStoryHelperApp._refresh_status

    # v5 compact presentation. The three actions are independent toggles, so
    # long-hold, repeated-key, and repeated-click can run at the same time.
    def _build_ui(self) -> None:
        outer = ctk.CTkFrame(self.root, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=18, pady=14)

        header = ctk.CTkFrame(outer, fg_color="transparent", height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.pack(side="left")
        ctk.CTkLabel(
            title_group,
            text="把你砌进神像里",
            font=("Microsoft YaHei UI", 26, "bold"),
            text_color=self.COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="多功能可同时开启 · 全局快捷键 · 一键急停",
            font=("Microsoft YaHei UI", 13),
            text_color=self.COLORS["muted"],
        ).pack(anchor="w", pady=(1, 0))
        self.permission_badge = ctk.CTkLabel(
            header,
            text="检查权限中",
            width=118,
            height=36,
            corner_radius=10,
            fg_color="#252D40",
            text_color=self.COLORS["muted"],
            font=("Microsoft YaHei UI", 13, "bold"),
        )
        self.permission_badge.pack(side="right", pady=5)

        status_card = ctk.CTkFrame(
            outer,
            height=70,
            corner_radius=14,
            fg_color=self.COLORS["card_alt"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        status_card.pack(fill="x", pady=(10, 9))
        status_card.pack_propagate(False)
        status_text = ctk.CTkFrame(status_card, fg_color="transparent")
        status_text.pack(side="left", fill="both", expand=True, padx=16, pady=7)
        self.connection_badge = ctk.CTkLabel(
            status_text,
            text="● 正在检测原神",
            font=("Microsoft YaHei UI", 20, "bold"),
            text_color=self.COLORS["muted"],
        )
        self.connection_badge.pack(anchor="w")
        self.connection_detail = ctk.CTkLabel(
            status_text,
            text="请稍候…",
            font=("Microsoft YaHei UI", 12),
            text_color=self.COLORS["muted"],
        )
        self.connection_detail.pack(anchor="w", pady=(2, 0))
        self.process_detail = ctk.CTkLabel(
            status_card,
            text="PID —",
            width=108,
            height=48,
            corner_radius=10,
            fg_color="#101624",
            text_color=self.COLORS["muted"],
            font=("Consolas", 12),
        )
        self.process_detail.pack(side="right", padx=13)

        self.tabs = ctk.CTkTabview(
            outer,
            height=355,
            corner_radius=14,
            fg_color=self.COLORS["card"],
            border_width=1,
            border_color=self.COLORS["border"],
            segmented_button_selected_color=self.COLORS["violet"],
            segmented_button_selected_hover_color=self.COLORS["violet_hover"],
            segmented_button_unselected_color="#242B3E",
            text_color=self.COLORS["text"],
        )
        self.tabs.pack(fill="x")
        control_tab = self.tabs.add("控制")
        settings_tab = self.tabs.add("按键设置")
        self._build_control_tab(control_tab)
        self._build_settings_tab(settings_tab)

        footer = ctk.CTkFrame(outer, fg_color="transparent", height=86)
        footer.pack(fill="x", pady=(8, 0))
        footer.pack_propagate(False)
        ctk.CTkButton(
            footer,
            text="收进托盘",
            width=102,
            height=32,
            corner_radius=9,
            fg_color="#252D40",
            hover_color="#333D55",
            font=("Microsoft YaHei UI", 12, "bold"),
            command=self._hide_to_tray,
        ).pack(side="left")
        self.mode_status = ctk.CTkLabel(
            footer,
            text="全部已停止",
            font=("Microsoft YaHei UI", 12, "bold"),
            text_color=self.COLORS["muted"],
        )
        self.mode_status.pack(side="left", padx=13)
        ctk.CTkButton(
            footer,
            text="退出",
            width=70,
            height=32,
            corner_radius=9,
            fg_color="transparent",
            border_width=1,
            border_color="#653747",
            hover_color="#3A2532",
            text_color=self.COLORS["red"],
            command=self.close,
        ).pack(side="right")

    def _build_control_tab(self, parent) -> None:
        ctk.CTkLabel(
            parent,
            text="每项独立开关，可同时开启多个功能",
            font=("Microsoft YaHei UI", 15, "bold"),
            text_color=self.COLORS["green"],
        ).pack(anchor="w", padx=14, pady=(11, 7))

        mode_stack = ctk.CTkFrame(parent, fg_color="transparent")
        mode_stack.pack(fill="x", padx=9)
        self.mode_button_colors = {
            MODE_PRESS_F: self.COLORS["violet"],
            MODE_CLICK: self.COLORS["pink"],
            MODE_HOLD_W: self.COLORS["blue"],
        }
        for mode in (MODE_PRESS_F, MODE_CLICK, MODE_HOLD_W):
            button = ctk.CTkButton(
                mode_stack,
                text="",
                height=78,
                corner_radius=12,
                fg_color="#252C40",
                hover_color="#343E57",
                border_width=1,
                border_color=self.mode_button_colors[mode],
                text_color="#FFFFFF",
                font=("Microsoft YaHei UI", 19, "bold"),
                command=lambda selected=mode: self._toggle_mode(selected),
            )
            button.pack(fill="x", padx=4, pady=3)
            self.mode_buttons[mode] = button

        self.stop_button = ctk.CTkButton(
            parent,
            text="",
            height=48,
            corner_radius=10,
            fg_color="#352430",
            hover_color="#4C2D3D",
            border_width=1,
            border_color="#87465C",
            text_color=self.COLORS["red"],
            font=("Microsoft YaHei UI", 16, "bold"),
            command=self._stop,
        )
        self.stop_button.pack(fill="x", padx=13, pady=(7, 8))

        interval_row = ctk.CTkFrame(parent, fg_color="transparent")
        interval_row.pack(fill="x", padx=14)
        ctk.CTkLabel(
            interval_row,
            text="连按 / 连点间隔",
            width=112,
            anchor="w",
            font=("Microsoft YaHei UI", 14, "bold"),
            text_color=self.COLORS["text"],
        ).pack(side="left")
        ctk.CTkSlider(
            interval_row,
            from_=60,
            to=600,
            number_of_steps=54,
            variable=self.interval_value,
            progress_color=self.COLORS["violet"],
            button_color=self.COLORS["pink"],
            button_hover_color="#FFD0F0",
            command=self._apply_interval,
        ).pack(side="left", fill="x", expand=True, padx=10)
        self.interval_value_label = ctk.CTkLabel(
            interval_row,
            text=f"{int(self.interval_value.get())} ms",
            width=70,
            height=27,
            corner_radius=8,
            fg_color="#101624",
            text_color=self.COLORS["pink"],
            font=("Consolas", 11, "bold"),
        )
        self.interval_value_label.pack(side="right")

        focus_row = ctk.CTkFrame(parent, fg_color="#1C2435", corner_radius=11)
        focus_row.pack(fill="x", padx=12, pady=(10, 6))
        focus_text = ctk.CTkFrame(focus_row, fg_color="transparent")
        focus_text.pack(side="left", fill="both", expand=True, padx=13, pady=8)
        ctk.CTkLabel(
            focus_text,
            text="启动新功能时切换到原神",
            font=("Microsoft YaHei UI", 15, "bold"),
            text_color=self.COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            focus_text,
            text="原神失焦后暂停；浏览器在前台时无法接收键鼠输入",
            font=("Microsoft YaHei UI", 11),
            text_color=self.COLORS["muted"],
        ).pack(anchor="w", pady=(1, 0))
        ctk.CTkSwitch(
            focus_row,
            text="",
            width=48,
            variable=self.auto_focus,
            progress_color=self.COLORS["green"],
            command=self._apply_auto_focus,
        ).pack(side="right", padx=13)

        self._refresh_button_texts()

    def _build_settings_tab(self, parent) -> None:
        action_row = ctk.CTkFrame(parent, fg_color="#1C2435", corner_radius=11)
        action_row.pack(fill="x", padx=12, pady=(11, 8))
        for index, (key, label, value) in enumerate((
            ("press_key", "连按动作键", str(self.settings["press_key"])),
            ("hold_key", "长按动作键", str(self.settings["hold_key"])),
        )):
            cell = ctk.CTkFrame(action_row, fg_color="transparent")
            cell.grid(row=0, column=index, sticky="ew", padx=10, pady=9)
            action_row.grid_columnconfigure(index, weight=1)
            ctk.CTkLabel(
                cell,
                text=label,
                font=("Microsoft YaHei UI", 12, "bold"),
                text_color=self.COLORS["muted"],
            ).pack(anchor="w")
            entry = ctk.CTkEntry(
                cell,
                height=42,
                corner_radius=8,
                fg_color="#101624",
                border_color=self.COLORS["border"],
                text_color=self.COLORS["text"],
                font=("Consolas", 16, "bold"),
            )
            entry.pack(fill="x", pady=(4, 0))
            entry.insert(0, value)
            self.action_entries[key] = entry

        hotkey_card = ctk.CTkFrame(parent, fg_color="transparent")
        hotkey_card.pack(fill="x", padx=14)
        labels = {
            "press": "切换连按",
            "click": "切换左键",
            "hold": "切换长按",
            "stop": "全部急停",
        }
        for row, key in enumerate(("press", "click", "hold", "stop")):
            ctk.CTkLabel(
                hotkey_card,
                text=labels[key],
                width=96,
                anchor="w",
                font=("Microsoft YaHei UI", 14, "bold"),
                text_color=self.COLORS["text"],
            ).grid(row=row, column=0, sticky="w", pady=4)
            entry = ctk.CTkEntry(
                hotkey_card,
                height=40,
                corner_radius=8,
                fg_color="#101624",
                border_color=self.COLORS["border"],
                text_color=self.COLORS["pink"],
                font=("Consolas", 15, "bold"),
                placeholder_text="例如 Ctrl+Alt+K",
            )
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)
            entry.insert(0, str(self.settings["hotkeys"][key]))
            hotkey_card.grid_columnconfigure(1, weight=1)
            self.hotkey_entries[key] = entry

        apply_row = ctk.CTkFrame(parent, fg_color="transparent")
        apply_row.pack(fill="x", padx=14, pady=(8, 0))
        self.setting_feedback = ctk.CTkLabel(
            apply_row,
            text="支持 Ctrl / Alt / Shift / Win 组合键",
            font=("Microsoft YaHei UI", 11),
            text_color=self.COLORS["muted"],
        )
        self.setting_feedback.pack(side="left")
        ctk.CTkButton(
            apply_row,
            text="应用并保存",
            width=126,
            height=42,
            corner_radius=9,
            fg_color=self.COLORS["violet"],
            hover_color=self.COLORS["violet_hover"],
            font=("Microsoft YaHei UI", 14, "bold"),
            command=self._apply_key_settings,
        ).pack(side="right")

    def _setup_tray(self) -> None:
        if pystray is None or Image is None or ImageDraw is None:
            return
        try:
            icon_image = Image.open(
                resource_path(os.path.join("assets", "raiden-app-icon-256.png"))
            ).convert("RGBA")
        except OSError:
            icon_image = Image.new("RGBA", (64, 64), (89, 72, 150, 255))

        def enabled(selected: str):
            return lambda _item: selected in self.engine.snapshot()[0]

        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", lambda *_: self._call_on_ui(self._restore_window), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("连按设定键", lambda *_: self._call_on_ui(lambda: self._toggle_mode(MODE_PRESS_F)), checked=enabled(MODE_PRESS_F)),
            pystray.MenuItem("连续点左键", lambda *_: self._call_on_ui(lambda: self._toggle_mode(MODE_CLICK)), checked=enabled(MODE_CLICK)),
            pystray.MenuItem("长按设定键", lambda *_: self._call_on_ui(lambda: self._toggle_mode(MODE_HOLD_W)), checked=enabled(MODE_HOLD_W)),
            pystray.MenuItem("全部停止", lambda *_: self._call_on_ui(self._stop)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda *_: self._call_on_ui(self.close)),
        )
        self._tray_icon = pystray.Icon("genshin_story_helper", icon_image, APP_TITLE, menu)
        threading.Thread(target=self._tray_icon.run, name="tray-icon", daemon=True).start()

    def _refresh_button_texts(self) -> None:
        if not self.mode_buttons:
            return
        active_modes = self.engine.snapshot()[0]
        hotkeys = self.settings["hotkeys"]
        labels = {
            MODE_PRESS_F: f"{hotkeys['press']}\n连按 {self.settings['press_key']}",
            MODE_CLICK: f"{hotkeys['click']}\n连续点左键",
            MODE_HOLD_W: f"{hotkeys['hold']}\n长按 {self.settings['hold_key']}",
        }
        for mode, button in self.mode_buttons.items():
            active = mode in active_modes
            button.configure(
                text=labels[mode],
                fg_color=self.mode_button_colors[mode] if active else "#252C40",
                border_width=2 if active else 1,
                border_color="#FFFFFF" if active else self.mode_button_colors[mode],
            )
        if hasattr(self, "stop_button"):
            self.stop_button.configure(text=f"全部急停   {hotkeys['stop']}")

    def _toggle_mode(self, mode: str) -> None:
        active_modes = self.engine.toggle(mode)
        if mode in active_modes and self.auto_focus.get():
            activate_game_window()
        self._update_mode_display()
        self._refresh_tray_menu()

    def _active_mode_text(self, active_modes: frozenset[str]) -> str:
        names = []
        for mode in (MODE_PRESS_F, MODE_CLICK, MODE_HOLD_W):
            if mode in active_modes:
                names.append(self._mode_name(mode))
        return " + ".join(names)

    def _update_mode_display(self, game_active: bool | None = None, game_window: int | None = None) -> None:
        active_modes = self.engine.snapshot()[0]
        if game_active is None:
            game_active = is_game_foreground()
        if not active_modes:
            text, color = "全部已停止", self.COLORS["muted"]
        elif game_active:
            text, color = "执行中：" + self._active_mode_text(active_modes), self.COLORS["green"]
        else:
            text, color = "已开启，等待原神焦点：" + self._active_mode_text(active_modes), self.COLORS["amber"]
        self.mode_status.configure(text=text, text_color=color)
        self._refresh_button_texts()

    def _refresh_status(self) -> None:
        if self._closing:
            return
        processes = find_game_processes()
        game_running = bool(processes)
        game_active = is_game_foreground()
        elevated = is_elevated()
        ready = bool(game_running and game_active and elevated)

        if not game_running:
            badge, detail, color, process_text = (
                "● 未检测到原神",
                "启动游戏后会自动检测",
                self.COLORS["muted"],
                "PID —",
            )
        else:
            pid, process_name = processes[0]
            process_text = f"{process_name}\n{pid}"
            if not elevated:
                badge, detail, color = (
                    "● 权限不足",
                    "请以管理员身份运行免安装版",
                    self.COLORS["red"],
                )
            elif game_active:
                badge, detail, color = (
                    "● 原神已激活 · 输入可执行",
                    "已开启的多个功能会同时执行",
                    self.COLORS["green"],
                )
            else:
                badge, detail, color = (
                    "● 原神已运行 · 输入已暂停",
                    "当前焦点属于其他窗口；切回原神后自动继续",
                    self.COLORS["amber"],
                )

        self.connection_badge.configure(text=badge, text_color=color)
        self.connection_detail.configure(text=detail)
        self.process_detail.configure(text=process_text)
        self.permission_badge.configure(
            text="✓ 权限正常" if elevated else "! 权限不足",
            fg_color="#173B35" if elevated else "#40232D",
            text_color=self.COLORS["green"] if elevated else self.COLORS["red"],
        )
        self._update_mode_display(game_active)

        if ready and self._last_ready is not True and self._tray_icon is not None:
            try:
                self._tray_icon.notify(
                    "原神已获得输入焦点，已开启的功能可以执行。",
                    "把你砌进神像里",
                )
            except Exception:
                pass
        self._last_ready = ready
        if self._tray_icon is not None:
            self._tray_icon.title = "把你砌进神像里 - " + (
                "输入可执行" if ready else "输入已暂停"
            )
        self._status_after_id = self.root.after(400, self._refresh_status)


def self_test() -> int:
    process_name, title = foreground_window_info()
    console_encoding = sys.stdout.encoding or "utf-8"
    safe_title = title.encode(console_encoding, errors="replace").decode(console_encoding)
    assert ctypes.sizeof(INPUT) in (28, 40), "Unexpected INPUT structure size"
    print("Windows input structures: OK")
    print(f"Foreground process: {process_name or '(unknown)'}")
    print(f"Foreground title: {safe_title or '(none)'}")
    print("Game detection: " + ("active" if is_game_foreground() else "inactive"))
    print(f"Game processes: {find_game_processes() or '(none)'}")
    print("Elevated: " + ("yes" if is_elevated() else "no"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--visual-test", action="store_true")
    options, _ = parser.parse_known_args()
    if options.self_test:
        return self_test()

    if ctk is None:
        user32.MessageBoxW(
            None,
            "缺少界面组件。请运行打包后的免安装版，或重新执行 build.ps1。",
            APP_TITLE,
            0x10,
        )
        return 1

    mutex_name = "Local\\GenshinStoryHelper-4A76C7D4-68C8-49C9-ACFC-17C7F12269C0"
    if options.smoke_test or options.visual_test:
        mutex_name += "-smoke-test"
    instance_mutex = kernel32.CreateMutexW(
        None,
        True,
        mutex_name,
    )
    if ctypes.get_last_error() == 183:
        user32.MessageBoxW(
            None,
            "把你砌进神像里已经在运行，请查看右下角系统托盘。",
            APP_TITLE,
            0x40,
        )
        if instance_mutex:
            kernel32.CloseHandle(instance_mutex)
        return 0

    try:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        # Counter Windows' 150% DPI scaling for layout coordinates; individual
        # controls use deliberately large dimensions and fonts above.
        ctk.set_widget_scaling(0.67)
        ctk.set_window_scaling(1.0)
        root = ctk.CTk()
        if options.smoke_test:
            root.withdraw()
        app = StoryHelperApp(root)
        if options.smoke_test:
            root.after(800, app.close)
        elif options.visual_test:
            root.after(5000, app.close)
        root.mainloop()
    finally:
        if instance_mutex:
            kernel32.CloseHandle(instance_mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
