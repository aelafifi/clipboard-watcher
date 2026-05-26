"""
clipboard_watcher/main.py

Listens for clipboard changes on Windows. When copied text starts with the
trigger prefix ("gpt:"), it strips the prefix and sends the rest to ChatGPT
via browser automation, waits for the response, copies it back to the
clipboard, and shows a "Job Done!" alert.

Requirements: pip install pywin32 selenium webdriver-manager
"""

import ctypes
import ctypes.wintypes
import os
import threading
import win32clipboard
import win32con
import win32gui
import win32api
from typing import List

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

WM_CLIPBOARDUPDATE = 0x031D
user32 = ctypes.windll.user32

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

# Copied text must start with this prefix to trigger ChatGPT.
# Example: copy "gpt: summarise this paragraph..." to trigger.
TRIGGER_PREFIX = "gpt:"

# A dedicated Chrome profile for this app.
# First launch: a browser window opens — log into ChatGPT.
# All subsequent launches reuse the saved session automatically.
BROWSER_PROFILE_DIR = os.path.expandvars(r"%APPDATA%\ClipboardWatcher\browser-profile")

# Set to True to run the browser invisibly in the background.
# Keep False while debugging so you can see what's happening.
HEADLESS = False


# ------------------------------------------------------------------
# Clipboard watcher (Win32 message loop)
# ------------------------------------------------------------------

class ClipboardWatcher:
    def __init__(self):
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc
        wc.lpszClassName = "ClipWatcher"
        wc.hInstance = win32api.GetModuleHandle(None)
        win32gui.RegisterClass(wc)

        # Message-only window — no visible UI
        self.hwnd = win32gui.CreateWindowEx(
            0, wc.lpszClassName, "ClipWatcher", 0,
            0, 0, 0, 0,
            -3, 0, wc.hInstance, None
        )

        user32.AddClipboardFormatListener(self.hwnd)
        self._last_seq = win32clipboard.GetClipboardSequenceNumber()
        print(f"Clipboard watcher started.")
        print(f'Copy text starting with "{TRIGGER_PREFIX}" to send it to ChatGPT.')

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_CLIPBOARDUPDATE:
            self._on_clipboard_change()
        elif msg == win32con.WM_DESTROY:
            user32.RemoveClipboardFormatListener(hwnd)
            win32gui.PostQuitMessage(0)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_clipboard_change(self):
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
    # Handlers
    # ------------------------------------------------------------------

    def handle_text(self, text: str):
        """Called whenever plain text is copied."""
        if not text.strip().lower().startswith(TRIGGER_PREFIX):
            print(f"[SKIP] {text[:60]!r}")
            return

        prompt = text[len(TRIGGER_PREFIX):].strip()
        print(f"[TRIGGER] Sending to ChatGPT: {prompt[:80]!r}")

        # Run in a background thread so the Win32 message loop isn't blocked
        threading.Thread(target=_ask_chatgpt, args=(prompt,), daemon=True).start()

    def handle_files(self, paths: List[str]):
        """Called whenever one or more files are copied (Ctrl+C in Explorer)."""
        print(f"[FILES] {paths}")
        # --- add your logic below ---

    def handle_other(self):
        """Called for clipboard formats we don't explicitly handle (images, etc.)."""
        print("[OTHER] Non-text/file clipboard content detected.")
        # --- add your logic below ---


# ------------------------------------------------------------------
# ChatGPT automation via Selenium (runs in a background thread)
# ------------------------------------------------------------------

def _ask_chatgpt(prompt: str):
    os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
    driver = None

    try:
        # ---- Build Chrome options ----
        options = Options()
        options.add_argument(f"--user-data-dir={BROWSER_PROFILE_DIR}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        if HEADLESS:
            options.add_argument("--headless=new")

        # webdriver-manager downloads the right ChromeDriver automatically
        # and caches it in %USERPROFILE%\.wdm\ for future runs
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        # ---- Navigate to ChatGPT ----
        driver.get("https://chatgpt.com/")

        wait = WebDriverWait(driver, 20)

        # Wait for the chat input to be ready
        input_box = wait.until(
            EC.element_to_be_clickable((By.ID, "prompt-textarea"))
        )
        input_box.click()
        input_box.send_keys(prompt)
        input_box.send_keys(Keys.ENTER)

        # Wait for ChatGPT to start generating (stop button appears) …
        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="stop-button"]'))
        )
        # … then wait for it to finish (stop button disappears)
        WebDriverWait(driver, 120).until(
            EC.invisibility_of_element((By.CSS_SELECTOR, '[data-testid="stop-button"]'))
        )

        # Grab the last assistant message
        responses = driver.find_elements(By.CSS_SELECTOR, '[data-message-author-role="assistant"]')
        if not responses:
            raise RuntimeError("Could not find assistant response on the page.")
        response_text = responses[-1].text

        driver.quit()

        # ---- Write response back to clipboard ----
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, response_text)
        win32clipboard.CloseClipboard()

        print(f"[DONE] Response copied to clipboard ({len(response_text)} chars).")
        user32.MessageBoxW(0, "Response copied to clipboard!", "Job Done!", 0)

    except Exception as exc:
        print(f"[ERROR] {exc}")
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        user32.MessageBoxW(0, f"Something went wrong:\n\n{exc}", "Clipboard Watcher — Error", 0)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    ClipboardWatcher()
    win32gui.PumpMessages()
