# SessionChat

**A lightweight chat overlay that follows your Roblox game session.**

[English](README.md) · [Русский](README.ru.md) · [Website](https://h1nchek.github.io/session-chat/) · [Download for Windows](https://github.com/h1nchek/session-chat/releases/latest)

---

## What is SessionChat?

SessionChat is an open-source real-time chat for playing Roblox together. The Windows overlay detects your active Roblox server from its local game log and connects you to the matching chat room.

> **Project status:** early-stage community project. The desktop client is Windows-only. Read the security notes before running or hosting a server.

## Features

- **Automatic session detection** — matches the current Roblox `PlaceId` and `JobId`.
- **In-game overlay** — click-through window, adjustable opacity, draggable header and quick **T** hotkey.
- **Server and experience chat** — talk to people in the same server or use `/global` for the whole experience.
- **Private rooms** — create a temporary room and invite friends with a 4-digit code.
- **Mentions and notifications** — highlight `@yourname` and optionally play a soft notification tone.
- **Chat controls** — local `/mute Nick`, nickname settings and basic server-side spam/scam filtering.
- **Android companion** — join a PC session by invite code or find an experience by name / PlaceId.

## Get started

### Windows app

1. Open [GitHub Releases](https://github.com/h1nchek/session-chat/releases).
2. Download `SessionChat.exe` from the latest release.
3. Run the application and choose a nickname.

No Python installation is needed when using the packaged executable.

### Run from source

Requirements: Windows, Python 3.10+, and the packages in `requirements.txt`.

```bash
python -m pip install -r requirements.txt
python client.py
```

The client uses `ws://127.0.0.1:8765` by default. Set `SERVER_URL` near the top of `client.py` to point to your own server. For a custom Roblox log directory, set the `ROBLOX_LOG_DIR` environment variable.

### Run the server

```bash
python -m pip install -r requirements.txt
python server.py
```

The server listens on `0.0.0.0:8765` by default. Configure your client to use the server's reachable address.

**Do not expose the current server directly to the public internet.** See [Security](#security-and-privacy).

## Using the overlay

| Control | Action |
| --- | --- |
| `T` | Open the chat input |
| `Enter` | Send a message |
| `Escape` | Close the input and return to click-through mode |
| Gear icon | Open nickname, opacity and room settings |
| Drag the header | Move the overlay while interactive |
| `/mute Nick` | Hide messages from a nickname locally |
| `/global` or `/global on` | Join the experience-wide chat |
| `/global off` | Return to the current server chat |
| `@YourNickname` | Mention a player |

Use **Settings → Join by code** to enter a friend's 4-digit room code, or choose **Create private** to create a temporary invite-only room.

## Android companion

The Android project is in `android/`. Open that folder in Android Studio and allow Gradle to sync.

The app supports:
- Joining a desktop player's exact session with a 4-digit invite code.
- Searching Roblox experiences by name.
- Entering a numeric `PlaceId` directly.
- Reading and sending chat messages.

For a local development server, configure the app's WebSocket URL. The default `ws://10.0.2.2:8765` is for the Android emulator when the server runs on the host computer.

## Security and privacy

SessionChat is an early-stage project, not a hardened public chat service.

- The current server does **not** provide account authentication, transport encryption, or persistent message history.
- The built-in rate limit and basic spam/scam filtering are not a replacement for authentication or human moderation.
- Room IDs are derived from local Roblox logs and are not independently verified by Roblox.
- Do not run an untrusted public server or expose port `8765 directly to the internet. For internet deployments, use a properly secured `wss://` endpoint, authentication, network protections and moderation.
- The overlay reads local Roblox log files to detect the active game session.

### Windows build transparency

Tagged releases are built by GitHub Actions. Release assets are intended to include:
- `SessionChat.exe` — Windows desktop client.
- `SHA256SUMS.txt` — checksum for integrity checking.
- GitHub build-provenance attestation — information about the source revision and build workflow.

A checksum can detect an altered download; it does **not** prove that software is malware-free. Build dependencies and the build environment are also part of the software supply chain.

## License

SessionChat is distributed under the **GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)**. See [LICENSE](LICENSE).

---

[Русская версия документации](README.ru.md) · [Website](https://h1nchek.github.io/session-chat/) · [Issues](https://github.com/h1nchek/session-chat/issues)
