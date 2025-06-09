import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List
import httpx
from fastapi.staticfiles import StaticFiles
app = FastAPI()

rooms: Dict[str, List[WebSocket]] = {}
available_bots = ["bot_1"]  # simple bot pool
joined_bots = {}

app.mount("/static", StaticFiles(directory="static", html=True), name="static")

@app.websocket("/ws/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    await websocket.accept()
    if call_id not in rooms:
        rooms[call_id] = []
    rooms[call_id].append(websocket)

    # Trigger bot join if not already in this call
    if call_id not in joined_bots:
        await check_and_add_bot(call_id)

    try:
        while True:
            # Receive raw audio bytes from client
            data = await websocket.receive_bytes()

            # Broadcast audio bytes to all peers except sender
            for peer in rooms[call_id]:
                if peer != websocket:
                    await peer.send_bytes(data)

    except WebSocketDisconnect:
        rooms[call_id].remove(websocket)
        # If bot leaves, mark bot as available again
        if call_id in joined_bots:
            bot_id = joined_bots.pop(call_id)
            available_bots.append(bot_id)

async def check_and_add_bot(call_id: str):
    if available_bots:
        bot_id = available_bots.pop(0)
        joined_bots[call_id] = bot_id
        print(f"Bot {bot_id} joining call {call_id}")

        # Notify bot service via HTTP
        
        async with httpx.AsyncClient() as client:
            await client.post("http://localhost:9000/join", json={"call_id": call_id})
    else:
        print("No bots available")