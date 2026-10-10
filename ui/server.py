"""
Basis console - web UI for the decoy-state BB84 eavesdropper-detection project.

Run from the project root:

    python -m ui                      # or
    python -m uvicorn ui.server:app --port 8000

then open http://127.0.0.1:8000
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# The project's scripts use paths relative to the repo root (models/, data/, outputs/).
os.chdir(PROJECT_ROOT)

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from ui import services  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Basis console", docs_url="/api/docs", redoc_url=None)


def _bad_request(exc: Exception):
    raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------- system

@app.get("/api/system")
def system() -> dict[str, Any]:
    try:
        card = services.model_card()
    except Exception as exc:
        card = {"available": False, "error": str(exc)}
    return {
        "capabilities": services.capabilities(),
        "model": card,
        "python": sys.version.split()[0],
    }


# ---------------------------------------------------------------- sessions

@app.post("/api/sessions")
async def create_session(params: dict[str, Any]):
    try:
        return await asyncio.to_thread(services.run_session, params)
    except (ValueError, FileNotFoundError) as exc:
        _bad_request(exc)


@app.get("/api/sessions")
def list_sessions():
    return services.session_history()


# ---------------------------------------------------------------- protocol

@app.post("/api/trace")
async def trace(params: dict[str, Any]):
    try:
        return await asyncio.to_thread(services.trace_bb84, params)
    except ValueError as exc:
        _bad_request(exc)


@app.get("/api/circuit")
async def circuit(bit: int, prep: str, measure: str, flipped: bool = False):
    if prep not in ("+", "x") or measure not in ("+", "x") or bit not in (0, 1):
        raise HTTPException(400, "bit must be 0/1 and bases must be '+' or 'x'")
    return await asyncio.to_thread(services.circuit_for, bit, prep, measure, flipped)


@app.post("/api/decoy")
async def decoy(params: dict[str, Any]):
    return await asyncio.to_thread(services.decoy_stats, params)


# ---------------------------------------------------------------- PQC

@app.post("/api/pqc/signature")
async def pqc_signature(params: dict[str, Any]):
    if not services.capabilities()["pqc"]:
        raise HTTPException(400, "pqcrypto is not installed")
    return await asyncio.to_thread(services.pqc_signature, params)


@app.post("/api/pqc/kem")
async def pqc_kem():
    if not services.capabilities()["pqc"]:
        raise HTTPException(400, "pqcrypto is not installed")
    return await asyncio.to_thread(services.pqc_kem)


# ---------------------------------------------------------------- evaluation

@app.get("/api/evaluation")
def evaluation():
    return services.evaluation_bundle()


@app.get("/api/evaluation/scenarios")
async def evaluation_scenarios():
    try:
        return await asyncio.to_thread(services.scenario_breakdown)
    except FileNotFoundError as exc:
        return {"available": False, "reason": str(exc)}


@app.get("/api/jobs")
def jobs():
    return services.job_catalog()


@app.post("/api/jobs/{kind}")
def start_job(kind: str):
    try:
        return services.start_job(kind)
    except ValueError as exc:
        _bad_request(exc)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = services.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@app.get("/figures/{name}")
def figure(name: str):
    path = (services.OUTPUTS_DIR / name).resolve()
    if path.parent != services.OUTPUTS_DIR.resolve() or path.suffix != ".png" or not path.exists():
        raise HTTPException(404, "figure not found")
    return FileResponse(path)


# ---------------------------------------------------------------- live monitor

def _apply(monitor: services.LinkMonitor, message: dict[str, Any]) -> str | None:
    s = monitor.settings
    cmd = message.get("cmd")
    if cmd == "attack":
        attack = message.get("type", "none")
        if attack not in services.ATTACK_TYPES:
            return "unknown attack type"
        s.attack_type = attack
        if "intensity" in message:
            s.intensity = max(0.05, min(1.0, float(message["intensity"])))
    elif cmd == "intensity":
        s.intensity = max(0.05, min(1.0, float(message["value"])))
    elif cmd == "noise":
        s.noise = max(0.0, min(0.15, float(message["value"])))
    elif cmd == "drift":
        s.drift = bool(message.get("value"))
    elif cmd == "interval":
        s.interval_ms = int(max(120, min(2000, int(message["value"]))))
    elif cmd == "reset":
        monitor.reset()
    return None


@app.websocket("/ws/link")
async def link_socket(ws: WebSocket):
    await ws.accept()
    try:
        monitor = await asyncio.to_thread(services.LinkMonitor)
    except Exception as exc:
        await ws.send_json({"type": "error", "message": str(exc)})
        await ws.close()
        return

    state = {"paused": False}

    async def receiver():
        while True:
            message = await ws.receive_json()
            if message.get("cmd") == "pause":
                state["paused"] = bool(message.get("value", True))
                continue
            error = _apply(monitor, message)
            if message.get("cmd") == "reset":
                await ws.send_json({"type": "reset"})
            await ws.send_json({
                "type": "settings",
                "settings": vars(monitor.settings),
                "error": error,
            })

    async def producer():
        await ws.send_json({"type": "settings", "settings": vars(monitor.settings)})
        while True:
            if not state["paused"]:
                frame = await asyncio.to_thread(monitor.step)
                await ws.send_json({"type": "window", **frame})
            await asyncio.sleep(monitor.settings.interval_ms / 1000)

    tasks = [asyncio.create_task(receiver()), asyncio.create_task(producer())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()


# ---------------------------------------------------------------- frontend

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


def main():
    import argparse
    import webbrowser

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Basis console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://{args.host}:{args.port}"
    print(f"Basis console running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        import threading

        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
