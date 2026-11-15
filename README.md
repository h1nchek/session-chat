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
- WebSocket server routes messages by room and limits each client to one message per second.
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

Set `SERVER_URL` near the top of `client.py`.

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

## Notes and limitations

- This is an early, minimal implementation, not a hardened public chat service.
- The client uses WinAPI polling for the global `T` hotkey. The key may also be received by the game.
- The server has no account authentication, encryption, moderation, or persistent history. Do not expose it directly to the public internet.
- The overlay is Windows-only. The WebSocket server can run on other platforms.
- Room IDs are based on values found in local Roblox logs; the server does not independently verify game-session membership.

## License

Distributed under the terms of the GNU Affero General Public License, version 3 or (at your option) any later version. See [LICENSE](LICENSE).
