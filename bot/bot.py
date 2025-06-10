import asyncio
import uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sockets.socket_manager import SocketManager
import os
from audio.audio_processor import AudioProcessor
from transcription.transcriber import Transcriber
from text_to_audio.edge_tts import EdgeTTSService
import logging
from config import Greetings,PauseText
from rag.neo4j import Neo4jQueryEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)
audio_processor = AudioProcessor()
transcriber=Transcriber()
tts_service=EdgeTTSService()
greetings=Greetings()
pause_text=PauseText()
app = FastAPI()

Neo4jQueryEngine.setup_llm()
query_engine = Neo4jQueryEngine()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust origins as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Stores: {bot_id: {"task": asyncio.Task, "manager": SocketManager}}
active_bots = {}
SOCKET_URL="localhost:8080"

async def on_receive(from_bot, data, message_type, socket_manager:SocketManager):
    """Example callback for handling received messages"""
    if message_type == "processed_audio":
        print(f"[Example] Received processed audio from {from_bot}:")
        print(f"  - Duration: {data['duration_seconds']:.2f}s")
        print(f"  - Sample rate: {data['sample_rate']}Hz")
        print(f"  - Buffer size: {len(data['audio_buffer'])} bytes")
        audio_array = data['audio_array']
        sample_rate = data['sample_rate']

        transcribed_text, is_empty = await transcriber.transcribe_audio(audio_array, sample_rate)

        if not is_empty:
            print(f"Transcribed Text: {transcribed_text}")
            await socket_manager.send_message(
                msg_type="transcription",
                data={"text": transcribed_text}
            )
        else:
            print("No speech detected or silence.")
        pause=pause_text.pick_random_greeting()
        pause_audio=await tts_service.text_to_audio_bytes(pause)
        await socket_manager.send_message(
                    msg_type="bot_message", 
                     data={"text": pause}
                 )
        await socket_manager.send_message(raw_audio=pause_audio)
        
        response=query_engine.query(transcribed_text)
        response_audio=await tts_service.text_to_audio_bytes(response)
        await socket_manager.send_message(
                    msg_type="bot_message", 
                     data={"text": response}
                 )
        await socket_manager.send_message(raw_audio=response_audio)
        # Optionally, send back the audio chunk (remove if not needed)

        
    elif message_type == "json":
        print(f"[Example] Received JSON from {from_bot}: {data}")
        
async def on_send(message):
    logger.info(f"[Received] {message}")
async def bot_join_call(call_id, bot_id):
    logger.info(f"[Received] {call_id}")
    manager = SocketManager(base_url=SOCKET_URL,call_id=call_id,bot_id=bot_id)  # pass call_id here
    try:
        await manager.connect( on_receive=on_receive, on_send=on_send)
        text_greetings=greetings.pick_random_greeting()
        greeting_audio=await tts_service.text_to_audio_bytes(text_greetings)
        await asyncio.sleep(1)
        await manager.send_message(
                    msg_type="bot_message", 
                     data={"text": text_greetings}
                 )
        await manager.send_message(raw_audio=greeting_audio)
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        
        print(f"[BOT] Bot {bot_id} is stopping...")
        await manager.disconnect()
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
