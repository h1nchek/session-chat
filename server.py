# SPDX-License-Identifier: AGPL-3.0-or-later
# SessionChat - minimal room-based WebSocket chat server.

import asyncio
import json
import re
import secrets
import time

import websockets

HOST = "0.0.0.0"
PORT = 8765
rooms = {}          # room_id -> set of websocket connections
nicknames = {}      # websocket -> nickname
last_message = {}   # websocket -> monotonic timestamp
last_message_text = {}
client_rooms = {}   # websocket -> set of joined room IDs
invite_codes = {}   # four-digit code -> temporary room ID

URL_PATTERN = re.compile(r"(?:https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|gg|ru|io|xyz)\b)", re.I)
SCAM_PATTERNS = (
    re.compile(r"free\s+robux", re.I),
    re.compile(r"\b(verify|confirm)\s+(your\s+)?(roblox\s+)?(account|password)\b", re.I),
    re.compile(r"\b(send|give|share)\s+(me\s+)?your\s+(password|login|cookie)\b", re.I),
    re.compile(r"\bclaim\s+(your\s+)?(free\s+)?(reward|prize|robux)\b", re.I),
    re.compile(r"\b(account|password)\s+(will be|is about to be)\s+(deleted|banned|locked)\b", re.I),
)


async def send_json(ws, payload):
    try:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        return True
    except websockets.exceptions.ConnectionClosed:
        return False


async def broadcast(room_ids, payload):
    targets = set()
    for room_id in room_ids:
        targets.update(rooms.get(room_id, ()))
    if not targets:
        return
    message = json.dumps(payload, ensure_ascii=False)
    results = await asyncio.gather(
        *(client.send(message) for client in targets),
        return_exceptions=True,
    )
    for client, result in zip(targets, results):
        if isinstance(result, Exception):
            for members in rooms.values():
                members.discard(client)


def make_invite_code():
    # Short-lived invitation, not an account credential. Codes are unique
    # while active and are removed when their room owner disconnects.
    for _ in range(100):
        code = f"{secrets.randbelow(10000):04d}"
        if code not in invite_codes:
            return code
    raise RuntimeError("No free room codes")


def suspicious_message(text):
    # Links are disabled in this minimal chat to reduce phishing risk.
    if URL_PATTERN.search(text):
        return "Links are disabled to help prevent phishing"
    if any(pattern.search(text) for pattern in SCAM_PATTERNS):
        return "Message blocked by the anti-scam filter"
    return None


async def handler(ws):
    joined_rooms = set()
    nickname = None
    invite_code = None
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        join = json.loads(raw)
        if not isinstance(join, dict) or join.get("type") != "join":
            return

        nickname = str(join.get("nickname", "Player")).strip()[:20] or "Player"
        room_code = str(join.get("room_code", "")).strip()
        place_id = str(join.get("place_id", "")).strip()
        room_id = str(join.get("room_id", "")).strip()[:100]
        game_place_id = ""

        if room_code:
            if len(room_code) != 4 or not room_code.isdigit():
                await send_json(ws, {"type": "error", "message": "Room code must be 4 digits"})
                return
            room_id = invite_codes.get(room_code, "")
            if not room_id:
                await send_json(ws, {"type": "error", "message": "Room code not found or expired"})
                return
        elif join.get("create_private"):
            room_id = "private:" + secrets.token_urlsafe(12)
        elif place_id:
            if not place_id.isdigit() or len(place_id) > 20:
                await send_json(ws, {"type": "error", "message": "Invalid PlaceId"})
                return
            room_id = f"place:{place_id}"
            game_place_id = place_id
        if not room_id:
            await send_json(ws, {"type": "error", "message": "A room code, PlaceId, or room_id is required"})
            return

        joined_rooms.add(room_id)
        # Desktop starts in its exact JobId room. /global explicitly adds
        # the shared PlaceId room. A private invite remains private.
        if join.get("share_code") and game_place_id:
            invite_code = make_invite_code()
            invite_codes[invite_code] = room_id
        elif join.get("create_private"):
            invite_code = make_invite_code()
            invite_codes[invite_code] = room_id
        if game_place_id:
            await send_json(ws, {"type": "game_context", "place_id": game_place_id})

        for joined_room in joined_rooms:
            rooms.setdefault(joined_room, set()).add(ws)
        client_rooms[ws] = joined_rooms
        nicknames[ws] = nickname
        last_message[ws] = 0.0
        last_message_text[ws] = ""

        await send_json(ws, {"type": "status", "message": "Connected"})
        if invite_code:
            await send_json(ws, {"type": "room_code", "code": invite_code})
        await broadcast(joined_rooms, {
            "type": "system", "message": f"{nickname} joined the chat"
        })

        async for raw in ws:
            try:
                packet = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(packet, dict):
                continue
            if packet.get("type") == "global":
                if not game_place_id:
                    await send_json(ws, {"type": "error", "message": "Global chat is available when a PlaceId is detected"})
                    continue
                global_room = f"place:{game_place_id}"
                if bool(packet.get("enabled")):
                    if global_room not in joined_rooms:
                        joined_rooms.add(global_room)
                        rooms.setdefault(global_room, set()).add(ws)
                    await send_json(ws, {"type": "global_status", "enabled": True, "place_id": game_place_id})
                    await broadcast({global_room}, {"type": "system", "message": f"{nickname} joined the global chat"})
                else:
                    if global_room in joined_rooms:
                        joined_rooms.discard(global_room)
                        members = rooms.get(global_room, set())
                        members.discard(ws)
                        if not members:
                            rooms.pop(global_room, None)
                    await send_json(ws, {"type": "global_status", "enabled": False, "place_id": game_place_id})
                continue
            if packet.get("type") != "message":
                continue

            text = str(packet.get("text", "")).strip()[:200]
            text = "".join(ch for ch in text if ch == "\t" or ord(ch) >= 32)
            if not text:
                continue

            now = time.monotonic()
            if now - last_message[ws] < 1.0:
                await send_json(ws, {
                    "type": "error",
                    "message": "Slow down: one message per second",
                })
                continue
            if text.casefold() == last_message_text[ws].casefold() and now - last_message[ws] < 15:
                await send_json(ws, {
                    "type": "error",
                    "message": "Repeated message blocked",
                })
                continue
            warning = suspicious_message(text)
            if warning:
                await send_json(ws, {"type": "error", "message": warning})
                continue

            last_message[ws] = now
            last_message_text[ws] = text
            await broadcast(joined_rooms, {
                "type": "message",
                "nickname": nickname,
                "text": text,
                "timestamp": int(time.time()),
            })

    except asyncio.TimeoutError:
        print("[TIMEOUT] Join packet not received")
    except websockets.exceptions.ConnectionClosed:
        pass
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[BAD PACKET] {exc}")
    except Exception as exc:
        print(f"[ERROR] {exc}")
    finally:
        if nickname is not None:
            nicknames.pop(ws, None)
            last_message.pop(ws, None)
            last_message_text.pop(ws, None)
            memberships = client_rooms.pop(ws, set())
            for joined_room in memberships:
                members = rooms.get(joined_room, set())
                members.discard(ws)
                if not members:
                    rooms.pop(joined_room, None)
            if invite_code:
                invite_codes.pop(invite_code, None)
            if memberships:
                await broadcast(memberships, {
                    "type": "system", "message": f"{nickname} left the chat"
                })
            print(f"[LEAVE] {nickname} ({', '.join(sorted(memberships))})")


async def main():
    print(f"SessionChat listening on ws://{HOST}:{PORT}")
    async with websockets.serve(
        handler,
        HOST,
        PORT,
        max_size=4096,
        ping_interval=20,
        ping_timeout=20,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
