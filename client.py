# SPDX-License-Identifier: AGPL-3.0-or-later
# SessionChat - Windows Roblox session overlay client.

import asyncio
import ctypes
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
import customtkinter as ctk
from pathlib import Path
from tkinter import simpledialog

import websockets

SERVER_URL = "ws://127.0.0.1:8765"
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Roblox" / "logs"
LOG_PATTERN = re.compile(
    r"Joining game '([a-f0-9-]{36})' place (\d+)", re.IGNORECASE
)
POLL_INTERVAL = 2.0
WINDOW_ALPHA = 0.90
PANEL_BG = "#151922"
SURFACE_BG = "#1D2430"
MUTED_FG = "#8490A3"
ACCENT = "#83B7FF"
MAX_MESSAGES = 100

if os.name != "nt":
    raise RuntimeError("SessionChat overlay client requires Windows.")

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
LWA_ALPHA = 0x00000002
VK_T = 0x54

if ctypes.sizeof(ctypes.c_void_p) == 8:
    get_window_long = user32.GetWindowLongPtrW
    set_window_long = user32.SetWindowLongPtrW
else:
    get_window_long = user32.GetWindowLongW
    set_window_long = user32.SetWindowLongW

get_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
get_window_long.restype = ctypes.c_ssize_t
set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
set_window_long.restype = ctypes.c_ssize_t


class LogWatcher(threading.Thread):
    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback
        self.running = True
        self.current_room = None

    def run(self):
        while self.running:
            try:
                files = list(LOG_DIR.glob("*.log"))
                if files:
                    latest = max(files, key=lambda p: p.stat().st_mtime)
                    with latest.open("r", encoding="utf-8", errors="ignore") as f:
                        matches = list(LOG_PATTERN.finditer(f.read()))
                    if matches:
                        job_id, place_id = matches[-1].groups()
                        room = f"{place_id}_{job_id}"
                        if room != self.current_room:
                            self.current_room = room
                            self.callback(room)
            except (OSError, PermissionError):
                pass
            except Exception as exc:
                print(f"[LOG ERROR] {exc}")
            time.sleep(POLL_INTERVAL)

    def stop(self):
        self.running = False


class ChatConnection(threading.Thread):
    def __init__(self, nickname, incoming):
        super().__init__(daemon=True)
        self.nickname = nickname
        self.incoming = incoming
        self.outgoing = queue.Queue()
        self.room_id = None
        self.running = True

    def change_room(self, room_id):
        self.room_id = room_id

    def send_message(self, text):
        if text.strip():
            self.outgoing.put(text.strip()[:200])

    async def receive(self, websocket):
        async for raw in websocket:
            try:
                packet = json.loads(raw)
                if isinstance(packet, dict):
                    self.incoming.put(packet)
            except (json.JSONDecodeError, TypeError):
                continue

    async def main_loop(self):
        while self.running:
            room = self.room_id
            if not room:
                await asyncio.sleep(0.25)
                continue
            try:
                self.incoming.put({
                    "type": "status", "message": f"Connecting to {room}..."
                })
                async with websockets.connect(
                    SERVER_URL,
                    open_timeout=5,
                    close_timeout=2,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=4096,
                ) as ws:
                    await ws.send(json.dumps({
                        "type": "join",
                        "room_id": room,
                        "nickname": self.nickname,
                    }, ensure_ascii=False))
                    self.incoming.put({
                        "type": "status", "message": f"Connected: {room}"
                    })
                    receiver = asyncio.create_task(self.receive(ws))
                    try:
                        while self.running and self.room_id == room:
                            if receiver.done():
                                await receiver
                                break
                            try:
                                text = self.outgoing.get_nowait()
                            except queue.Empty:
                                text = None
                            if text is not None:
                                await ws.send(json.dumps({
                                    "type": "message", "text": text
                                }, ensure_ascii=False))
                            await asyncio.sleep(0.05)
                    finally:
                        receiver.cancel()
                        await asyncio.gather(receiver, return_exceptions=True)
            except Exception as exc:
                self.incoming.put({
                    "type": "status", "message": f"Connection error: {exc}"
                })
            if self.running:
                await asyncio.sleep(2)

    def run(self):
        asyncio.run(self.main_loop())

    def stop(self):
        self.running = False


class OverlayChat:
    def __init__(self, nickname):
        self.nickname = nickname
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.title("SessionChat")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", WINDOW_ALPHA)
        self.root.configure(fg_color=PANEL_BG)
        self.root.geometry("360x250+30+100")
        self.root.resizable(False, False)

        self.input_active = False
        self.muted_users = set()
        self.incoming = queue.Queue()
        self.messages = []
        self.previous_t = False

        # Compact, low-contrast HUD. The whole window stays click-through
        # until the player opens the composer with T.
        shell = ctk.CTkFrame(
            self.root, fg_color=PANEL_BG, corner_radius=16,
            border_width=1, border_color="#30394A"
        )
        shell.pack(fill="both", expand=True, padx=1, pady=1)

        header = ctk.CTkFrame(
            shell, fg_color=SURFACE_BG, corner_radius=12, height=36
        )
        header.pack(fill="x")
        header.pack_propagate(False)

        brand = ctk.CTkLabel(
            header, text="●  SESSIONCHAT", text_color="#DCE7F7",
            font=("Segoe UI", 10, "bold"), anchor="w"
        )
        brand.pack(side="left", fill="y")
        self.room_badge = ctk.CTkLabel(
            header, text="WAITING", text_color=MUTED_FG,
            font=("Segoe UI", 8, "bold")
        )
        self.room_badge.pack(side="right", fill="y")

        status_row = ctk.CTkFrame(shell, fg_color="transparent")
        status_row.pack(fill="x", padx=11, pady=(8, 3))
        self.status = ctk.CTkLabel(
            status_row, text="Looking for Roblox session…",
            text_color=MUTED_FG, font=("Segoe UI", 9), anchor="w"
        )
        self.status.pack(side="left", fill="x", expand=True)

        self.chat = ctk.CTkTextbox(
            shell, fg_color="#171D27", text_color="#D7DEEA",
            font=("Segoe UI", 9), corner_radius=11,
            border_width=0, wrap="word", activate_scrollbars=False
        )
        self.chat.pack(fill="both", expand=True, padx=8, pady=(0, 7))
        self.chat._textbox.tag_configure(
            "system", foreground="#778397",
            font=("Segoe UI", 8, "italic")
        )
        self.chat._textbox.tag_configure(
            "nickname", foreground=ACCENT,
            font=("Segoe UI", 9, "bold")
        )
        self.chat._textbox.tag_configure("body", foreground="#D7DEEA")

        self.input_frame = ctk.CTkFrame(
            shell, fg_color=SURFACE_BG, corner_radius=11,
            border_width=1, border_color="#34445C"
        )
        self.entry = ctk.CTkEntry(
            self.input_frame, fg_color=SURFACE_BG,
            text_color="#F3F6FC", placeholder_text="Write a message…",
            border_width=0, corner_radius=9, height=34,
            font=("Segoe UI", 10)
        )
        self.entry.pack(fill="x", padx=10, pady=9)
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<Escape>", self.on_escape)

        footer = ctk.CTkFrame(shell, fg_color=SURFACE_BG,
                              corner_radius=10, height=27)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        self.footer = ctk.CTkLabel(
            footer, text="T  open chat     /mute name",
            text_color="#78869A", font=("Segoe UI", 8), anchor="w"
        )
        self.footer.pack(side="left", fill="y")
        self.hint = ctk.CTkLabel(
            footer, text="ESC  close",
            text_color="#78869A", font=("Segoe UI", 8), anchor="e"
        )
        self.hint.pack(side="right", fill="y")

        self.connection = ChatConnection(nickname, self.incoming)
        self.connection.start()
        self.watcher = LogWatcher(self.connection.change_room)
        self.watcher.start()

        self.root.update_idletasks()
        self.hwnd = self.root.winfo_id()
        self.enable_clickthrough()
        self.root.after(50, self.poll_keyboard)
        self.root.after(100, self.process_messages)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def set_alpha(self):
        user32.SetLayeredWindowAttributes(
            self.hwnd, 0, int(255 * WINDOW_ALPHA), LWA_ALPHA
        )

    def enable_clickthrough(self):
        style = get_window_long(self.hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST
        set_window_long(self.hwnd, GWL_EXSTYLE, style)
        self.set_alpha()

    def disable_clickthrough(self):
        style = get_window_long(self.hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TOPMOST
        style &= ~WS_EX_TRANSPARENT
        set_window_long(self.hwnd, GWL_EXSTYLE, style)
        self.set_alpha()

    def activate_input(self):
        if self.input_active:
            return
        self.input_active = True
        self.input_frame.pack(fill="x", before=self.chat)
        self.disable_clickthrough()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.entry.focus_set()

    def deactivate_input(self):
        if not self.input_active:
            return
        self.input_active = False
        self.input_frame.pack_forget()
        self.enable_clickthrough()

    def poll_keyboard(self):
        if not self.root.winfo_exists():
            return
        key_down = bool(user32.GetAsyncKeyState(VK_T) & 0x8000)
        if key_down and not self.previous_t and not self.input_active:
            self.activate_input()
        self.previous_t = key_down
        self.root.after(50, self.poll_keyboard)

    def on_enter(self, event=None):
        if not self.input_active:
            return "break"
        text = self.entry.get().strip()
        self.entry.delete(0, "end")
        if text.lower().startswith("/mute "):
            target = text[6:].strip()
            if target:
                self.muted_users.add(target.casefold())
                self.add_system_message(f"Muted {target} locally")
        elif text:
            self.connection.send_message(text)
        self.deactivate_input()
        return "break"

    def on_escape(self, event=None):
        self.deactivate_input()
        return "break"

    def add_system_message(self, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"[SYSTEM] {text}\n", "system")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def add_chat_message(self, nickname, text):
        if nickname.casefold() in self.muted_users:
            return
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{nickname}: ", "nickname")
        self.chat.insert("end", f"{text}\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")
        self.messages.append((nickname, text))
        if len(self.messages) > MAX_MESSAGES:
            self.messages.pop(0)
            self.chat.configure(state="normal")
            self.chat.delete("1.0", "2.0")
            self.chat.configure(state="disabled")

    def process_messages(self):
        if not self.root.winfo_exists():
            return
        while True:
            try:
                packet = self.incoming.get_nowait()
            except queue.Empty:
                break
            kind = packet.get("type")
            if kind == "message":
                self.add_chat_message(
                    str(packet.get("nickname", "Player"))[:20],
                    str(packet.get("text", ""))[:200],
                )
            elif kind == "system":
                self.add_system_message(str(packet.get("message", "")))
            elif kind == "status":
                message = str(packet.get("message", ""))
                self.status.configure(text=message)
                self.room_badge.configure(
                    text="ONLINE" if message.startswith("Connected:") else "CONNECTING",
                    fg="#8FD6B0" if message.startswith("Connected:") else "#D9B978"
                )
            elif kind == "error":
                self.add_system_message(str(packet.get("message", "")))
        self.root.after(100, self.process_messages)

    def close(self):
        self.watcher.stop()
        self.connection.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.mainloop()


def main():
    dialog = tk.Tk()
    dialog.withdraw()
    nickname = simpledialog.askstring(
        "SessionChat", "Enter your nickname:", parent=dialog
    )
    dialog.destroy()
    if not nickname or not nickname.strip():
        return
    OverlayChat(nickname.strip()[:20]).run()


if __name__ == "__main__":
    main()
