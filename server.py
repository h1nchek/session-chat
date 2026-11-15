# SPDX-License-Identifier: AGPL-3.0-or-later
# SessionChat - minimal room-based WebSocket chat server.

import asyncio
import json
import time

import websockets

HOST = "0.0.0.0"
PORT = 8765
rooms = {}          # room_id -> set of websocket connections
nicknames = {}      # websocket -> nickname
last_message = {}   # websocket -> monotonic timestamp


async def send_json(ws, payload):
    try:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        return True
    except websockets.exceptions.ConnectionClosed:
        return False


async def broadcast(room_id, payload):
    clients = list(rooms.get(room_id, ()))
    if not clients:
        return
    message = json.dumps(payload, ensure_ascii=False)
    results = await asyncio.gather(
        *(client.send(message) for client in clients),
        return_exceptions=True,
    )
    for client, result in zip(clients, results):
        if isinstance(result, Exception):
            rooms.get(room_id, set()).discard(client)


async def handler(ws):
    room_id = None
    nickname = None
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        join = json.loads(raw)
        if not isinstance(join, dict) or join.get("type") != "join":
            return

        room_id = str(join.get("room_id", "")).strip()[:100]
        nickname = str(join.get("nickname", "Player")).strip()[:20] or "Player"
        if not room_id:
            return

        rooms.setdefault(room_id, set()).add(ws)
        nicknames[ws] = nickname
        last_message[ws] = 0.0

        await send_json(ws, {"type": "status", "message": "Connected"})
        await broadcast(room_id, {
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
            await broadcast(room_id, {
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
            members = rooms.get(room_id, set())
            members.discard(ws)
            if not members and room_id in rooms:
                rooms.pop(room_id, None)
            if room_id:
                await broadcast(room_id, {
                    "type": "system", "message": f"{nickname} left the chat"
                })
            print(f"[LEAVE] {nickname} ({room_id})")


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
