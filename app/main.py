from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from . import glossary
from .translate import available as translator_ready
from .translate import translate

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

HOST_TOKEN = os.getenv("HOST_TOKEN", "change-me-before-tea-party")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

app = FastAPI(title="TKU Live Translate", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class Room:
    def __init__(self, room_id: str) -> None:
        self.id = room_id
        self.live = False
        self.host: WebSocket | None = None
        self.listeners: set[WebSocket] = set()
        self.history: list[dict[str, Any]] = []
        self.lock = asyncio.Lock()

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "live": self.live,
            "listeners": len(self.listeners),
            "history": self.history[-40:],
        }


rooms: dict[str, Room] = {}


def get_room(room_id: str) -> Room:
    room_id = (room_id or "tea930").strip()[:32] or "tea930"
    if room_id not in rooms:
        rooms[room_id] = Room(room_id)
    return rooms[room_id]


def public_url(path: str) -> str:
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}{path}"
    return path


def check_host_token(token: str | None) -> None:
    if not HOST_TOKEN:
        return
    if (token or "") != HOST_TOKEN:
        raise HTTPException(status_code=401, detail="bad host token")


class GlossaryIn(BaseModel):
    zh: str
    en: str
    aliases: list[str] = []
    lock: bool = True
    cat: str = "term"


class PushIn(BaseModel):
    room: str
    zh: str
    token: str
    final: bool = True


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "translator": translator_ready(),
        "glossary_terms": len(glossary.terms()),
        "rooms": {
            k: {"live": v.live, "listeners": len(v.listeners), "lines": len(v.history)}
            for k, v in rooms.items()
        },
    }


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC / "host.html")


@app.get("/host")
async def host_page() -> FileResponse:
    return FileResponse(STATIC / "host.html")


@app.get("/r/{room_id}")
async def room_page(room_id: str) -> FileResponse:
    return FileResponse(STATIC / "room.html")


@app.get("/api/room/{room_id}")
async def room_api(room_id: str) -> dict[str, Any]:
    room = get_room(room_id)
    data = room.snapshot()
    data["qr_url"] = public_url(f"/r/{room.id}")
    data["translator"] = translator_ready()
    return data


@app.get("/api/glossary")
async def get_glossary() -> dict[str, Any]:
    return glossary.load()


@app.post("/api/glossary")
async def post_glossary(body: GlossaryIn, x_host_token: str | None = Header(default=None)) -> dict[str, Any]:
    check_host_token(x_host_token)
    return glossary.upsert(body.model_dump())


@app.post("/api/push")
async def push_text(body: PushIn) -> dict[str, Any]:
    check_host_token(body.token)
    room = get_room(body.room)
    event = await finalize(room, body.zh, body.final)
    return event


async def finalize(room: Room, zh: str, final: bool) -> dict[str, Any]:
    zh = glossary.normalize_zh((zh or "").strip())
    if not zh:
        return {"type": "empty"}
    if not final:
        event = {"type": "partial", "zh": zh, "en": "", "t": int(time.time() * 1000)}
        await broadcast(room, event, include_host=True)
        return event
    en = await translate(zh)
    event = {
        "type": "final",
        "id": uuid.uuid4().hex[:10],
        "zh": zh,
        "en": en,
        "t": int(time.time() * 1000),
    }
    async with room.lock:
        room.live = True
        room.history.append(event)
        room.history = room.history[-200:]
    await broadcast(room, event, include_host=True)
    await broadcast(
        room,
        {"type": "room", "listeners": len(room.listeners), "live": room.live},
        include_host=True,
    )
    return event


async def broadcast(room: Room, payload: dict[str, Any], include_host: bool = False) -> None:
    targets = set(room.listeners)
    if include_host and room.host is not None:
        targets.add(room.host)
    dead: list[WebSocket] = []
    for ws in targets:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        room.listeners.discard(ws)
        if room.host is ws:
            room.host = None


@app.websocket("/ws/host")
async def ws_host(ws: WebSocket, room: str = "tea930", token: str = "") -> None:
    if HOST_TOKEN and token != HOST_TOKEN:
        await ws.close(code=1008)
        return
    await ws.accept()
    state = get_room(room)
    if state.host is not None:
        try:
            await state.host.close()
        except Exception:
            pass
    state.host = ws
    state.live = True
    await ws.send_json(
        {
            "type": "hello",
            "role": "host",
            **state.snapshot(),
            "qr_url": public_url(f"/r/{state.id}"),
            "translator": translator_ready(),
        }
    )
    try:
        while True:
            data = await ws.receive_json()
            kind = data.get("type")
            if kind in {"zh", "text", "utterance"}:
                await finalize(state, data.get("text") or data.get("zh") or "", bool(data.get("final", True)))
            elif kind == "ping":
                await ws.send_json({"type": "pong"})
            elif kind == "stop":
                state.live = False
                await broadcast(
                    state,
                    {"type": "room", "listeners": len(state.listeners), "live": False},
                    include_host=True,
                )
    except WebSocketDisconnect:
        pass
    finally:
        if state.host is ws:
            state.host = None
            state.live = False
            await broadcast(state, {"type": "room", "listeners": len(state.listeners), "live": False})


@app.websocket("/ws/listen")
async def ws_listen(ws: WebSocket, room: str = "tea930") -> None:
    await ws.accept()
    state = get_room(room)
    state.listeners.add(ws)
    await ws.send_json({"type": "hello", "role": "listen", **state.snapshot()})
    await broadcast(
        state,
        {"type": "room", "listeners": len(state.listeners), "live": state.live},
        include_host=True,
    )
    try:
        while True:
            data = await ws.receive_text()
            if data in {"ping", '{"type":"ping"}'}:
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        state.listeners.discard(ws)
        await broadcast(
            state,
            {"type": "room", "listeners": len(state.listeners), "live": state.live},
            include_host=True,
        )
