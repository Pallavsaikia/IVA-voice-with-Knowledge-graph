import asyncio
import uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sockets.socket_manager import SocketManager  # Assumed updated to accept bot_id on init and has connect() and stop()
import os
from audiox import AudioProcessor
audio_processor = AudioProcessor()
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust origins as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import logging
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)
os.makedirs("audio", exist_ok=True)

# Stores: {bot_id: {"task": asyncio.Task, "manager": SocketManager}}
active_bots = {}

async def on_receive(from_bot, data, message_type, socket_manager:SocketManager):
    
    call_id = socket_manager.call_id

    should_send, audio_bytes = audio_processor.process_audio_chunk(call_id, data)

    # if should_send and audio_bytes:
    #     await socket_manager.send_message(
    #         raw_audio=audio_bytes  # Send as hex string over WebSocket
    #     )
    #     logger.info(f"[AudioProcessor] Sent processed audio for call {call_id}")
    # else:
    #     logger.debug(f"[AudioProcessor] No audio to send for call {call_id}")

async def on_send(message):
    logger.info(f"[Received] {message}")
async def bot_join_call(call_id, bot_id):
    logger.info(f"[Received] {call_id}")
    manager = SocketManager(call_id=call_id,bot_id=bot_id)  # pass call_id here
    try:
        await manager.connect( on_receive=on_receive, on_send=on_send)
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        
        print(f"[BOT] Bot {bot_id} is stopping...")
        await manager.disconnect_bot(bot_id)
        print(f"[BOT] Bot {bot_id} has stopped.")
    except Exception as e:
        print(f"[BOT] Error in bot_join_call for bot {bot_id}: {e}")

@app.post("/join")
async def join_call(request: Request):
    data = await request.json()
    call_id = data.get("room_id")
    print(call_id)
    if not call_id:
        return {"error": "Missing call_id"}

    bot_id = f"bot_{uuid.uuid4().hex[:8]}"

    if bot_id in active_bots:
        return {"status": "bot already active", "bot_id": bot_id}

    task = asyncio.create_task(bot_join_call(call_id, bot_id))
    active_bots[bot_id] = {"task": task, "call_id": call_id}

    return {"status": "bot joining", "bot_id": bot_id, "call_id": call_id}

@app.post("/leave")
async def leave_call(request: Request):
    data = await request.json()
    bot_id = data.get("bot_id")
    if not bot_id:
        return {"error": "Missing bot_id"}

    if bot_id in active_bots:
        task = active_bots[bot_id]["task"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        del active_bots[bot_id]
        print(f"[BOT] Bot {bot_id} disconnected")
        return {"status": "bot left"}

    return {"status": "bot not found"}
