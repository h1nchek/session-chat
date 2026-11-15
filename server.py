# SPDX-License-Identifier: AGPL-3.0-or-later
# SessionChat - minimal room-based WebSocket chat server.

import asyncio
import json
import secrets
import time

import websockets

HOST = "0.0.0.0"
PORT = 8765
rooms = {}          # room_id -> set of websocket connections
nicknames = {}      # websocket -> nickname
last_message = {}   # websocket -> monotonic timestamp
client_rooms = {}   # websocket -> set of joined room IDs
invite_codes = {}   # four-digit code -> private instance room ID


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
    # Codes are temporary, in-memory invitations, not account credentials.
    for _ in range(100):
        code = f"{secrets.randbelow(10000):04d}"
        if code not in invite_codes:
            return code
    raise RuntimeError("No free room codes")


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

        if room_code:
            if len(room_code) != 4 or not room_code.isdigit():
                await send_json(ws, {"type": "error", "message": "Room code must be 4 digits"})
                return
            room_id = invite_codes.get(room_code, "")
            if not room_id:
                await send_json(ws, {"type": "error", "message": "Room code not found or expired"})
                return
        elif place_id:
            if not place_id.isdigit() or len(place_id) > 20:
                await send_json(ws, {"type": "error", "message": "Invalid PlaceId"})
                return
            room_id = f"place:{place_id}"
        if not room_id:
            await send_json(ws, {"type": "error", "message": "A room code, PlaceId, or room_id is required"})
            return

        joined_rooms.add(room_id)
        # Desktop clients join their exact Roblox server and the game-wide
        # PlaceId room. Mobile PlaceId users therefore share chat across servers.
        if join.get("share_code") and "_" in room_id:
            parsed_place_id = room_id.split("_", 1)[0]
            if parsed_place_id.isdigit():
                joined_rooms.add(f"place:{parsed_place_id}")
                invite_code = make_invite_code()
                invite_codes[invite_code] = room_id

        for joined_room in joined_rooms:
            rooms.setdefault(joined_room, set()).add(ws)
        client_rooms[ws] = joined_rooms
        nicknames[ws] = nickname
        last_message[ws] = 0.0

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
            if not isinstance(packet, dict) or packet.get("type") != "message":
                continue

            text = str(packet.get("text", "")).strip()[:200]
            if not text:
                continue

            now = time.monotonic()
            if now - last_message[ws] < 1.0:
                await send_json(ws, {
                    "type": "error",
                    "message": "Rate limit: one message per second",
                })
                continue

            last_message[ws] = now
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
            memberships = client_rooms.pop(ws, set())
            for joined_room in memberships:
                members = rooms.get(joined_room, set())
                members.discard(ws)
                if not members:
                    rooms.pop(joined_room, None)
            # Remove invitation when its owning desktop session disconnects.
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
