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
import winsound
import customtkinter as ctk
from pathlib import Path
from tkinter import simpledialog

import websockets

SERVER_URL = "ws://127.0.0.1:8765"
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", ""))
DEFAULT_LOG_DIR = LOCAL_APP_DATA / "Roblox" / "logs"
# Bloxstrap and Fishstrap launch the same Roblox game runtime. In the usual
# setup its game-session logs remain in Roblox/logs. Allow custom locations
# for portable or non-standard installations via ROBLOX_LOG_DIR.
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

    def log_directories(self):
        candidates = []
        custom_dir = os.environ.get("ROBLOX_LOG_DIR", "").strip()
        if custom_dir:
            candidates.append(Path(os.path.expandvars(custom_dir)).expanduser())
        candidates.append(DEFAULT_LOG_DIR)

        # Keep only unique existing directories. The launcher name is not
        # used as a discriminator: Bloxstrap/Fishstrap normally start the
        # same Roblox client, whose session log lives in Roblox/logs.
        result = []
        seen = set()
        for directory in candidates:
            try:
                key = str(directory.resolve()).casefold()
                if key not in seen and directory.is_dir():
                    seen.add(key)
                    result.append(directory)
            except OSError:
                continue
        return result

    def run(self):
        while self.running:
            try:
                files = []
                for directory in self.log_directories():
                    files.extend(directory.glob("*.log"))
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
        self.join_request = None
        self.manual_join = False
        self.running = True
        self.reconnect_requested = threading.Event()

    def change_room(self, room_id):
        if self.manual_join:
            return
        self.room_id = room_id

    def join_invite_code(self, code):
        self.manual_join = True
        self.join_request = {"room_code": code}
        self.reconnect_requested.set()

    def create_private_room(self):
        self.manual_join = True
        self.join_request = {"create_private": True}
        self.reconnect_requested.set()

    def set_nickname(self, nickname):
        self.nickname = nickname
        self.reconnect_requested.set()

    def send_message(self, text):
        if text.strip():
            self.outgoing.put({"type": "message", "text": text.strip()[:200]})

    def set_global(self, enabled):
        self.outgoing.put({"type": "global", "enabled": bool(enabled)})

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
            if not room and not self.join_request:
                await asyncio.sleep(0.25)
                continue
            if self.reconnect_requested.is_set():
                self.reconnect_requested.clear()
            target = (
                "invite room" if self.join_request and "room_code" in self.join_request
                else "new private room" if self.join_request
                else room
            )
            try:
                self.incoming.put({
                    "type": "status", "message": f"Connecting to {target}..."
                })
                async with websockets.connect(
                    SERVER_URL,
                    open_timeout=5,
                    close_timeout=2,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=4096,
                ) as ws:
                    place_id = room.split("_", 1)[0] if room and "_" in room else ""
                    join_packet = {
                        "type": "join",
                        "room_id": room or "",
                        "place_id": place_id,
                        "share_code": bool(place_id.isdigit()),
                        "nickname": self.nickname,
                    }
                    if self.join_request:
                        join_packet.update(self.join_request)
                    await ws.send(json.dumps(join_packet, ensure_ascii=False))
                    self.incoming.put({
                        "type": "status", "message": f"Connected: {room}"
                    })
                    receiver = asyncio.create_task(self.receive(ws))
                    try:
                        while (
                            self.running
                            and self.room_id == room
                            and not self.reconnect_requested.is_set()
                        ):
                            if receiver.done():
                                await receiver
                                break
                            try:
                                text = self.outgoing.get_nowait()
                            except queue.Empty:
                                text = None
                            if text is not None:
                                packet = text if isinstance(text, dict) else {
                                    "type": "message", "text": text
                                }
                                await ws.send(json.dumps(packet, ensure_ascii=False))
                            await asyncio.sleep(0.05)
                    finally:
                        receiver.cancel()
                        await asyncio.gather(receiver, return_exceptions=True)
            except Exception as exc:
                self.incoming.put({
                    "type": "status", "message": f"Connection error: {exc}"
                })
            if self.reconnect_requested.is_set():
                self.reconnect_requested.clear()
                continue
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
        self.root.configure(fg_color="#0D1118")
        self.root.geometry("480x250+30+100")
        self.root.resizable(False, False)

        self.input_active = False
        self.muted_users = set()
        self.incoming = queue.Queue()
        self.messages = []
        self.previous_t = False
        self.window_alpha = WINDOW_ALPHA
        self.drag_origin = None
        self.settings_visible = False
        self.global_enabled = False
        self.sound_enabled = True

        # Compact, low-contrast HUD. The whole window stays click-through
        # until the player opens the composer with T.
        shell = ctk.CTkFrame(
            self.root, fg_color=PANEL_BG, corner_radius=16,
            border_width=1, border_color="#30394A"
        )
        shell.pack(fill="both", expand=True, padx=2, pady=2)

        header = ctk.CTkFrame(
            shell, fg_color=SURFACE_BG, corner_radius=12, height=36
        )
        header.pack(fill="x")
        header.pack_propagate(False)

        brand = ctk.CTkLabel(
            header, text="●  SESSIONCHAT", text_color="#DCE7F7",
            font=("Segoe UI", 10, "bold"), anchor="w"
        )
        brand.pack(side="left", fill="y", padx=(10, 0))
        self.gear_button = ctk.CTkButton(
            header, text="⚙", width=30, height=28,
            corner_radius=9, fg_color="transparent",
            hover_color="#30394A", text_color="#AAB8CC",
            font=("Segoe UI Symbol", 14),
            command=self.toggle_settings
        )
        self.gear_button.pack(side="right", padx=(0, 5), pady=3)
        self.close_button = ctk.CTkButton(
            header, text="×", width=27, height=28,
            corner_radius=9, fg_color="transparent",
            hover_color="#5A3038", text_color="#E5A8AE",
            font=("Segoe UI", 15, "bold"), command=self.close
        )
        self.close_button.pack(side="right", padx=(0, 5), pady=3)
        self.sound_button = ctk.CTkButton(
            header, text="♪ ON", width=48, height=28,
            corner_radius=9, fg_color="transparent",
            hover_color="#30394A", text_color="#AAB8CC",
            font=("Segoe UI", 9, "bold"), command=self.toggle_sound
        )
        self.sound_button.pack(side="right", padx=(0, 3), pady=3)
        self.room_badge = ctk.CTkLabel(
            header, text="WAITING", text_color=MUTED_FG,
            font=("Segoe UI", 8, "bold")
        )
        self.room_badge.pack(side="right", fill="y", padx=(0, 7))
        self.online_label = ctk.CTkLabel(
            header, text="Online: —", text_color="#AAB8CC",
            font=("Segoe UI", 8), anchor="e"
        )
        self.online_label.pack(side="right", fill="y", padx=(0, 7))

        status_row = ctk.CTkFrame(shell, fg_color="transparent")
        status_row.pack(fill="x", padx=11, pady=(8, 3))
        self.status = ctk.CTkLabel(
            status_row, text="Looking for Roblox session…",
            text_color=MUTED_FG, font=("Segoe UI", 9), anchor="w"
        )
        self.status.pack(side="left", fill="x", expand=True)

        self.settings_frame = ctk.CTkFrame(
            shell, fg_color=SURFACE_BG, corner_radius=11,
            border_width=1, border_color="#34445C"
        )
        settings_title = ctk.CTkLabel(
            self.settings_frame, text="OVERLAY SETTINGS",
            text_color="#DCE7F7", font=("Segoe UI", 9, "bold"),
            anchor="w"
        )
        settings_title.pack(fill="x", padx=10, pady=(9, 4))
        self.nickname_entry = ctk.CTkEntry(
            self.settings_frame, height=30, corner_radius=8,
            placeholder_text="Nickname", font=("Segoe UI", 9)
        )
        self.nickname_entry.insert(0, nickname)
        self.nickname_entry.pack(fill="x", padx=9, pady=3)
        self.save_nickname_button = ctk.CTkButton(
            self.settings_frame, text="Save nickname",
            height=27, corner_radius=8, font=("Segoe UI", 8, "bold"),
            command=self.save_nickname
        )
        self.save_nickname_button.pack(fill="x", padx=9, pady=(2, 6))

        self.private_code_entry = ctk.CTkEntry(
            self.settings_frame, height=29, corner_radius=8,
            placeholder_text="4-digit room code", font=("Segoe UI", 9)
        )
        self.private_code_entry.pack(fill="x", padx=9, pady=(1, 4))
        room_actions = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        room_actions.pack(fill="x", padx=9, pady=(0, 6))
        self.join_code_button = ctk.CTkButton(
            room_actions, text="Join by code", height=27, corner_radius=8,
            font=("Segoe UI", 8, "bold"), command=self.join_room_by_code
        )
        self.join_code_button.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.create_room_button = ctk.CTkButton(
            room_actions, text="Create private", height=27, corner_radius=8,
            fg_color="#34445C", hover_color="#405675",
            font=("Segoe UI", 8, "bold"), command=self.create_private_room
        )
        self.create_room_button.pack(side="left", fill="x", expand=True, padx=(3, 0))
        self.done_settings_button = ctk.CTkButton(
            self.settings_frame, text="Done  ·  return to game",
            height=25, corner_radius=8, fg_color="#30394A",
            hover_color="#3B4960", text_color="#DCE7F7",
            font=("Segoe UI", 8), command=self.deactivate_input
        )
        self.done_settings_button.pack(fill="x", padx=9, pady=(0, 5))
        self.exit_button = ctk.CTkButton(
            self.settings_frame, text="Exit SessionChat",
            height=25, corner_radius=8, fg_color="#55323A",
            hover_color="#70404A", text_color="#F2C5C9",
            font=("Segoe UI", 8, "bold"), command=self.close
        )
        self.exit_button.pack(fill="x", padx=9, pady=(0, 7))
        opacity_row = ctk.CTkFrame(
            self.settings_frame, fg_color="transparent"
        )
        opacity_row.pack(fill="x", padx=9, pady=(0, 8))
        self.opacity_label = ctk.CTkLabel(
            opacity_row, text="Opacity 90%",
            text_color=MUTED_FG, font=("Segoe UI", 8)
        )
        self.opacity_label.pack(side="left")
        self.opacity_slider = ctk.CTkSlider(
            opacity_row, from_=45, to=100, number_of_steps=55,
            width=145, height=14, command=self.change_opacity
        )
        self.opacity_slider.set(WINDOW_ALPHA * 100)
        self.opacity_slider.pack(side="right", padx=(8, 0))

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
        self.chat._textbox.tag_configure(
            "mention", foreground="#FFF1B8", background="#39452F",
            font=("Segoe UI", 9, "bold")
        )

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

        # Dragging is enabled only while the overlay is interactive.
        for widget in (header, brand, self.room_badge):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag_window)

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
            self.hwnd, 0, int(255 * self.window_alpha), LWA_ALPHA
        )
        self.root.attributes("-alpha", self.window_alpha)

    def toggle_settings(self):
        if not self.input_active:
            return
        if self.settings_visible:
            self.settings_frame.pack_forget()
            self.settings_visible = False
        else:
            self.settings_frame.pack(fill="x", padx=8, pady=(0, 6),
                                     before=self.chat)
            self.settings_visible = True

    def toggle_sound(self):
        self.sound_enabled = not self.sound_enabled
        self.sound_button.configure(
            text="♪ ON" if self.sound_enabled else "♪ OFF",
            text_color="#AAB8CC" if self.sound_enabled else MUTED_FG
        )

    def play_notification(self):
        if not self.sound_enabled:
            return
        try:
            winsound.Beep(660, 85)
        except RuntimeError:
            pass

    def change_opacity(self, value):
        self.window_alpha = max(0.45, min(1.0, float(value) / 100))
        self.opacity_label.configure(text=f"Opacity {round(self.window_alpha * 100)}%")
        self.set_alpha()

    def save_nickname(self):
        nickname = self.nickname_entry.get().strip()[:20]
        if not nickname:
            self.add_system_message("Nickname cannot be empty")
            return
        self.nickname = nickname
        self.connection.set_nickname(nickname)
        self.nickname_entry.delete(0, "end")
        self.nickname_entry.insert(0, nickname)
        self.add_system_message(f"Nickname changed to {nickname}")

    def join_room_by_code(self):
        code = self.private_code_entry.get().strip()
        if len(code) != 4 or not code.isdigit():
            self.add_system_message("Enter a valid 4-digit room code")
            return
        self.connection.join_invite_code(code)
        self.add_system_message(f"Joining private room with code {code}…")

    def create_private_room(self):
        self.connection.create_private_room()
        self.add_system_message("Creating a private room…")

    def start_drag(self, event):
        if not self.input_active:
            return
        self.drag_origin = (
            event.x_root - self.root.winfo_x(),
            event.y_root - self.root.winfo_y()
        )

    def drag_window(self, event):
        if not self.input_active or self.drag_origin is None:
            return
        x = event.x_root - self.drag_origin[0]
        y = event.y_root - self.drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

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
        self.settings_frame.pack_forget()
        self.settings_visible = False
        self.drag_origin = None
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
        if text.casefold() in ("/global", "/global on"):
            self.global_enabled = True
            self.connection.set_global(True)
            self.add_system_message("Global chat enabled")
            self.room_badge.configure(text="GLOBAL")
        elif text.casefold() == "/global off":
            self.global_enabled = False
            self.connection.set_global(False)
            self.add_system_message("Global chat disabled")
            self.room_badge.configure(text="LOCAL")
        elif text.lower().startswith("/mute "):
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
        is_mention = bool(re.search(
            rf"(?<![\w])@{re.escape(self.nickname)}(?![\w])",
            text, re.IGNORECASE
        ))
        self.chat.configure(state="normal")
        line_start = self.chat.index("end-1c")
        self.chat.insert("end", f"{nickname}: ", "nickname")
        self.chat.insert("end", text)
        if is_mention:
            line_end = self.chat.index("end-1c")
            self.chat.tag_add("mention", line_start, line_end)
        self.chat.insert("end", "\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")
        self.messages.append((nickname, text))
        if nickname.casefold() != self.nickname.casefold():
            self.play_notification()
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
                    text="ONLINE" if message.startswith("Connected") else "CONNECTING",
                    fg="#8FD6B0" if message.startswith("Connected") else "#D9B978"
                )
            elif kind == "online_counts":
                server_count = max(0, int(packet.get("server", 0)))
                game_count = max(0, int(packet.get("game", 0)))
                self.online_label.configure(
                    text=f"Online: {server_count} на сервере / {game_count} в игре"
                )
            elif kind == "room_code":
                code = str(packet.get("code", ""))[:4]
                self.add_system_message(f"Room invite code: {code}  · share with friends")
                self.footer.configure(text=f"ROOM CODE  {code}     T  open chat")
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
