from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import numpy as np
import io
import soundfile as sf
from transcription.transcriber import TranscriptionSession

router = APIRouter()


@router.websocket("/ws/transcribe")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            text = TranscriptionSession.transcribe_full(audio_np)
            await websocket.send_text(text)
    except WebSocketDisconnect:
        print("Client disconnected")
