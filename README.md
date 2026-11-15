# SessionChat

Minimalist real-time game overlay chat with automatic Roblox session detection.

**License:** GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later).

## Features

- Detects the latest Roblox log in `%LOCALAPPDATA%\Roblox\logs`.
- Extracts the most recent `JobId` and `PlaceId` and joins room `PlaceId_JobId`.
- Windows CustomTkinter overlay with rounded corners, transparency, and click-through mode.
- Press **T** to make the overlay interactive and open the chat input; **Enter** sends and **Escape** closes it.
- While interactive, use the **gear** to change nickname and opacity, or drag the header to reposition the overlay. Click **Done** (or press Escape in the input) to restore click-through mode.
- Local `/mute Nick` command.
- `/global`, `/global on`, and `/global off` toggle a cross-server chat shared by all SessionChat users in the same `PlaceId`.
- Create temporary private rooms and invite friends with a 4-digit code; desktop and Android clients can join with the same code.
- Join a friend's room from the PC overlay through **Settings → Join by code**.
- Server-side chat filter limits message frequency, blocks repeated messages, and rejects links and common account/Robux scam phrases.
- Nicknames are limited to 20 characters and messages to 200 characters.

## Requirements

- Python 3.10 or newer
- Windows for the overlay client
- `websockets`
- `customtkinter`

Install the dependency:

```bash
python -m pip install websockets customtkinter
```

## Run the server

On the host machine:

```bash
python server.py
```

The server listens on `0.0.0.0:8765`.

## Configure and run the client

Set `SERVER_URL` near the top of `client.py`. If your launcher uses a non-standard game-log directory, set `ROBLOX_LOG_DIR` to that folder before starting the client.

For a server on the same computer:

```python
SERVER_URL = "ws://127.0.0.1:8765"
```

For another computer on your LAN, use its LAN IP address, for example:

```python
SERVER_URL = "ws://192.168.1.100:8765"
```

Then run:

```bash
python client.py
```

Enter a nickname when prompted. When Roblox writes a matching session line to its log, the client automatically joins the corresponding room.

## Chat commands

| Key / command | Action |
| --- | --- |
| `T` | Open the input |
| `Enter` | Send the message |
| `Escape` | Close the input |
| `/mute Nick` | Hide messages from that nickname locally |
| `/global` or `/global on` | Join the shared chat for the current `PlaceId`, across all Roblox `JobId` servers |
| `/global off` | Leave the PlaceId-wide chat and keep the current server chat |

## Launcher compatibility

The client does not need to identify whether Roblox was started by the official launcher, Bloxstrap, or Fishstrap. It watches the Roblox game-session log directory used by the running game client. Standard installations should work without launcher-specific configuration. If a custom setup writes the game log elsewhere, configure `ROBLOX_LOG_DIR`. This compatibility is based on the shared Roblox runtime/log format and has not yet been verified against every launcher version.

## Android companion app (initial build)

A native Android companion app is in `android/`. It currently supports:

- Joining a PC player's exact Roblox server with the temporary **4-digit room code** shown by the desktop overlay (in its footer and system chat).
- Joining a friend's exact PC session with a 4-digit invite code.
- Searching Roblox experiences by name, selecting a result, and joining the shared chat for its `PlaceId`.
- Pasting a numeric `PlaceId` into the same game search field to join directly.
- Setting a nickname, reading chat, and sending messages.

Joining by PlaceId on Android opens the shared chat across all Roblox servers for that experience. On desktop, `/global` (or `/global on`) joins that same PlaceId-wide chat while retaining the current JobId room; `/global off` leaves it. The 4-digit code instead joins the exact desktop session. Codes are temporary, held in server memory, and expire when the desktop session that published the code disconnects or the server restarts.

### Build Android app

Open the `android/` directory in Android Studio and let Gradle sync. Build and install the `app` configuration. On the first screen, set **WebSocket server URL** to the address reachable from the phone, for example `ws://192.168.1.100:8765` for a server on the same Wi-Fi network. The default `ws://10.0.2.2:8765` is intended for the Android emulator when the server runs on the development computer.

The server must be reachable from the phone and its port must be allowed through the host firewall. For internet use, deploy the server behind a secure WebSocket endpoint (`wss://`) and add proper authentication, TLS, and moderation before exposing it publicly. The current Android prototype uses plain WebSockets and is intended for development/testing, not an untrusted public server.

## Notes and limitations

- This is an early, minimal implementation, not a hardened public chat service.
- The client uses WinAPI polling for the global `T` hotkey. The key may also be received by the game.
- The server has no account authentication, transport encryption, or persistent history. Its basic anti-spam/anti-phishing filter is not a substitute for human moderation. Do not expose it directly to the public internet.
- The overlay is Windows-only. The WebSocket server can run on other platforms.
- Room IDs are based on values found in local Roblox logs; the server does not independently verify game-session membership.

## License

Distributed under the terms of the GNU Affero General Public License, version 3 or (at your option) any later version. See [LICENSE](LICENSE).
