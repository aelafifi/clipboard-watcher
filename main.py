"""
clipboard_watcher/main.py

Listens for clipboard changes on Windows and calls handle_*() with the copied
content so you can plug in any custom decision logic you want.

Requirements: pip install pywin32
"""

import ctypes
import ctypes.wintypes
from typing import List
import win32clipboard
import win32con
import win32gui
import win32api

WM_CLIPBOARDUPDATE = 0x031D

user32 = ctypes.windll.user32


class ClipboardWatcher:
    def __init__(self):
        # Register a message-only window class
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc
        wc.lpszClassName = "ClipWatcher"
        wc.hInstance = win32api.GetModuleHandle(None)
        class_atom = win32gui.RegisterClass(wc)

        # HWND_MESSAGE (-3) creates a message-only window — no visible UI
        self.hwnd = win32gui.CreateWindowEx(
            0, class_atom, "ClipWatcher", 0,
            0, 0, 0, 0,
            -3, 0, wc.hInstance, None
        )

        # AddClipboardFormatListener is in user32.dll, not wrapped by win32clipboard
        user32.AddClipboardFormatListener(self.hwnd)
        self._last_seq = win32clipboard.GetClipboardSequenceNumber()
        print("Clipboard watcher started. Press Ctrl+C to stop.")

    # ------------------------------------------------------------------
    # Win32 window procedure — called by Windows on every message
    # ------------------------------------------------------------------
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_CLIPBOARDUPDATE:
            self._on_clipboard_change()
        elif msg == win32con.WM_DESTROY:
            user32.RemoveClipboardFormatListener(hwnd)
            win32gui.PostQuitMessage(0)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # ------------------------------------------------------------------
    # Called every time the clipboard changes
    # ------------------------------------------------------------------
    def _on_clipboard_change(self):
        # Guard against re-entrant notifications (e.g. if handle() writes to
        # the clipboard itself)
        seq = win32clipboard.GetClipboardSequenceNumber()
        if seq == self._last_seq:
            return
        self._last_seq = seq

        try:
            win32clipboard.OpenClipboard()

            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                self.handle_text(text)

            elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                files = win32clipboard.GetClipboardData(win32con.CF_HDROP)
                self.handle_files(list(files))

            else:
                self.handle_other()

        except Exception as exc:
            print(f"[ClipboardWatcher] error reading clipboard: {exc}")
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # YOUR CUSTOM LOGIC GOES HERE
    # ------------------------------------------------------------------

    def handle_text(self, text: str):
        """Called whenever plain text is copied."""
        print(f"[TEXT] {text!r}")

        # --- add your logic below ---
        # Examples:
        #   if text.startswith("http"):
        #       print("  -> URL detected")

    def handle_files(self, paths: List[str]):
        """Called whenever one or more files are copied (Ctrl+C in Explorer)."""
        print(f"[FILES] {paths}")

        # --- add your logic below ---

    def handle_other(self):
        """Called for clipboard formats we don't explicitly handle (images, etc.)."""
        print("[OTHER] Non-text/file clipboard content detected.")

        # --- add your logic below ---


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    ClipboardWatcher()
    win32gui.PumpMessages()
