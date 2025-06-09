import asyncio
import websockets
import numpy as np
from faster_whisper import WhisperModel
import io
import soundfile as sf
import sounddevice as sd
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from scipy.signal import resample_poly
import os
import time
import uuid
import json

from rag.neo4j import Neo4jQueryEngine
from gtts import gTTS
from text_to_audio.generator import GTTSService, TTSCache
import random

# ---------- Setup ----------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or specify origins like ["http://localhost:8000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
model = WhisperModel("base", compute_type="int8", device="cpu")
audio_buffer = bytearray()
os.makedirs("audio", exist_ok=True)

Neo4jQueryEngine.setup_llm()
query_engine = Neo4jQueryEngine()
tts_service = GTTSService()
tts_cache = TTSCache(tts_service)
WAIT_TEXT = ["Just a sec.", "Uhmm give me a sec", "Please be on line"]

# Store active bot connections
active_bots = {}

@app.post("/join")
async def join_call(request: Request):
    data = await request.json()
    call_id = data["room_id"]
    print(f"[BOT] Received join request for call_id: {call_id}")
    
    # Check if bot already exists for this room
    if call_id in active_bots:
        print(f"[BOT] Bot already active for room {call_id}")
        return {"status": "bot already active", "bot_id": active_bots[call_id]["bot_id"]}
    
    # Generate unique bot ID
    bot_id = f"bot_{uuid.uuid4().hex[:8]}"
    
    # Start bot task
    task = asyncio.create_task(bot_join_call(call_id, bot_id))
    active_bots[call_id] = {"bot_id": bot_id, "task": task}
    
    return {"status": "bot joining", "bot_id": bot_id}

@app.post("/leave")
async def leave_call(request: Request):
    data = await request.json()
    call_id = data["room_id"]
    
    if call_id in active_bots:
        active_bots[call_id]["task"].cancel()
        del active_bots[call_id]
        return {"status": "bot left"}
    
    return {"status": "bot not found"}

async def send_message(websocket, msg_type, data=None, to_clients=None):
    """Send a structured message through WebSocket"""
    message = {
        "type": msg_type,
        "data": data or {},
        "to": to_clients or [],
        "timestamp": int(time.time() * 1000)
    }
    await websocket.send(json.dumps(message))

async def bot_join_call(call_id: str, bot_id: str):
    uri = f"ws://localhost:8080/ws?room={call_id}&clientId={bot_id}&type=agent"
    print(f"[BOT] Connecting to {uri}")
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"[BOT] Bot {bot_id} connected to room {call_id}")

            global audio_buffer

            silence_threshold = 0.02
            silence_duration_ms = 1500
            original_sample_rate = 48000
            target_sample_rate = 16000
            up = target_sample_rate
            down = original_sample_rate

            bytes_per_sample = 2  # int16
            channels = 1
            silent_duration = 0.0
            is_processing = False

            # Send initial greeting
            await send_message(websocket, "bot_message", {
                "text": "Hi! I'm your AI assistant. I'm ready to help with any questions you have."
            })

            while True:
                try:
                    message = await websocket.recv()
                    
                    # Handle JSON messages
                    if isinstance(message, str):
                        try:
                            msg_data = json.loads(message)
                            print(f"[BOT] Received message: {msg_data}")
                            
                            # Ignore messages from self
                            if msg_data.get("from") == bot_id:
                                continue
                            
                            if msg_data.get("type") == "welcome":
                                print(f"[BOT] Welcome message received: {msg_data}")
                            elif msg_data.get("type") == "client_joined":
                                client_info = msg_data.get("data", {})
                                if client_info.get("clientType") == "user":
                                    await send_message(websocket, "bot_message", {
                                        "text": f"Hello! I see you've joined the call. How can I assist you today?"
                                    })
                            elif msg_data.get("type") == "client_left":
                                client_info = msg_data.get("data", {})
                                if client_info.get("clientType") == "user":
                                    print(f"[BOT] User {client_info.get('clientId')} left the call")
                            
                        except json.JSONDecodeError:
                            print(f"[BOT] Received non-JSON string: {message}")
                        continue
                    
                    # Handle binary audio data
                    if isinstance(message, bytes):
                        if is_processing:
                            continue  # Skip audio processing if already processing
                            
                        audio_buffer.extend(message)

                        chunk_samples = len(message) // (bytes_per_sample * channels)
                        chunk_duration = chunk_samples / original_sample_rate

                        audio_int16 = np.frombuffer(message, dtype=np.int16)
                        audio_float = audio_int16.astype(np.float32) / 32768.0
                        audio_16k = resample_poly(audio_float, up, down)

                        energy = np.sqrt(np.mean(audio_16k ** 2))

                        if energy < silence_threshold:
                            silent_duration += chunk_duration
                        else:
                            silent_duration = 0.0

                        min_buffer_len = target_sample_rate * 2 * 2  # 2s buffer

                        if silent_duration >= silence_duration_ms / 1000.0 and len(audio_buffer) > min_buffer_len:
                            audio_int16_full = np.frombuffer(audio_buffer, dtype=np.int16)
                            audio_float_full = audio_int16_full.astype(np.float32) / 32768.0
                            audio_16k_full = resample_poly(audio_float_full, up, down)
                            max_energy = np.max(np.abs(audio_16k_full))

                            if max_energy < silence_threshold:
                                print("[BOT] Buffer contains only silence, skipping transcription.")
                                audio_buffer = bytearray()
                                silent_duration = 0.0
                            else:
                                print(f"[BOT] {silent_duration:.2f}s silence detected. Processing audio chunk...")
                                is_processing = True
                                await transcribe_and_respond(audio_buffer, target_sample_rate, up, down, websocket)
                                audio_buffer = bytearray()
                                silent_duration = 0.0
                                is_processing = False
                    
                except websockets.exceptions.ConnectionClosed:
                    print(f"[BOT] WebSocket connection closed for bot {bot_id}")
                    break
                except Exception as e:
                    print(f"[BOT] Error in bot_join_call: {e}")
                    break
                    
    except Exception as e:
        print(f"[BOT] Failed to connect: {e}")
    finally:
        # Clean up
        if call_id in active_bots:
            del active_bots[call_id]
            print(f"[BOT] Cleaned up bot {bot_id} for room {call_id}")

async def transcribe_and_respond(buffer: bytearray, target_sample_rate, up, down, websocket):
    print("[BOT] Transcribing buffered audio...")

    try:
        audio_int16 = np.frombuffer(buffer, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0
        audio_16k = resample_poly(audio_float, up=up, down=down) if up != down else audio_float

        wav_io = io.BytesIO()
        sf.write(wav_io, audio_16k, target_sample_rate, format='WAV')
        wav_io.seek(0)

        segments, _ = model.transcribe(wav_io, language="en")
        text = "".join(segment.text for segment in segments).strip()

        if text:
            print(f"[BOT] Transcription result: {text}")
            
            # Send transcription to users
            await send_message(websocket, "transcription", {"text": text})
            
            # Send wait message
            wait_text = random.choice(WAIT_TEXT)
            await send_message(websocket, "bot_message", {"text": wait_text})
            
            # Generate wait audio
            wait_audio = tts_cache.get_audio_bytes(wait_text)
            await websocket.send(wait_audio)
            
            # Get response from query engine
            response = query_engine.query(text)
            print(f"[BOT] Response: {response}")

            # Send text response
            await send_message(websocket, "bot_message", {"text": str(response)})

            # Generate and send TTS response
            tts_audio = tts_service.text_to_audio_bytes(str(response))
            await websocket.send(tts_audio)
            
    except Exception as e:
        print(f"[BOT] Error in transcribe_and_respond: {e}")
        # Send error message
        await send_message(websocket, "bot_message", {
            "text": "Sorry, I encountered an error processing your request."
        })

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)