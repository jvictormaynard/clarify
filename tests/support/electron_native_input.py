"""Windows input for the isolated packaged Electron smoke test."""

import ctypes
from ctypes import wintypes
import sys


def native_pill_input(request):
    if sys.platform != "win32":
        raise RuntimeError("Native desktop input requires Windows")
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user.SendMessageW.restype = ctypes.c_ssize_t
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.GetForegroundWindow.restype = wintypes.HWND
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        action = request["action"]
        if action == "move":
            user.SetCursorPos(int(request["x"]), int(request["y"]))
        elif action in ("down", "up"):
            user.mouse_event(2 if action == "down" else 4, 0, 0, 0, 0)
        elif action == "key":
            foreground_pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(
                user.GetForegroundWindow(), ctypes.byref(foreground_pid)
            )
            if foreground_pid.value != request["pid"]:
                raise RuntimeError("The test window does not have keyboard focus")
            key = {"ArrowDown": 0x28, "ArrowUp": 0x26, "Enter": 0x0D}[request["key"]]
            user.keybd_event(key, 0, 0, 0)
            user.keybd_event(key, 0, 2, 0)
        elif action != "bounds":
            raise ValueError("Unsupported native test input")
        matches = []

        class GuiThreadInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("active", wintypes.HWND),
                ("focus", wintypes.HWND),
                ("capture", wintypes.HWND),
                ("menu", wintypes.HWND),
                ("moving", wintypes.HWND),
                ("caret", wintypes.HWND),
                ("caretRect", wintypes.RECT),
            ]

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            thread = user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == request["pid"] and user.IsWindowVisible(hwnd):
                rect = wintypes.RECT()
                user.GetWindowRect(hwnd, ctypes.byref(rect))
                if rect.right - rect.left > 400 and 100 < rect.bottom - rect.top < 700:
                    info = GuiThreadInfo()
                    info.cbSize = ctypes.sizeof(info)
                    user.GetGUIThreadInfo(thread, ctypes.byref(info))
                    cursor = wintypes.POINT()
                    user.GetCursorPos(ctypes.byref(cursor))
                    hit = user.SendMessageW(
                        hwnd, 0x84, 0, (cursor.x & 0xFFFF) | ((cursor.y & 0xFFFF) << 16)
                    )
                    matches.append(
                        dict(
                            x=rect.left,
                            y=rect.top,
                            width=rect.right - rect.left,
                            height=rect.bottom - rect.top,
                            capture=bool(info.capture),
                            foreground=user.GetAncestor(user.GetForegroundWindow(), 2)
                            == hwnd,
                            hit=hit,
                            receives=user.GetAncestor(user.WindowFromPoint(cursor), 2)
                            == hwnd,
                        )
                    )
            return True

        user.EnumWindows(visit, 0)
        return matches[0] if matches else None
    finally:
        user.SetThreadDpiAwarenessContext(previous)
