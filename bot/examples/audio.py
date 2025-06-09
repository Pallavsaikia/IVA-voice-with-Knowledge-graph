import queue
import sys
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
import threading
import time
from pynput import keyboard
import asyncio

model_size = "base"
model = WhisperModel(model_size, compute_type="int8", device="cpu")

sample_rate = 16000
block_duration = 3.0
block_size = int(sample_rate * block_duration)
audio_queue = queue.Queue()

stream = None
stream_lock = threading.Lock()
listening = False
stop_event = threading.Event()

def audio_callback(indata, frames, time_, status):
    if status:
        print(status, file=sys.stderr)
    audio_queue.put(indata.copy())

async def transcribe_worker(result_queue: asyncio.Queue):
    audio_buffer = np.zeros((0,), dtype=np.float32)
    loop = asyncio.get_event_loop()

    def get_audio():
        try:
            return audio_queue.get(timeout=0.1)
        except queue.Empty:
            return None

    while not stop_event.is_set():
        chunk = await loop.run_in_executor(None, get_audio)
        if chunk is None:
            continue

        chunk = chunk.flatten().astype(np.float32) / 32768.0
        audio_buffer = np.concatenate((audio_buffer, chunk))

        while len(audio_buffer) >= block_size:
            audio_to_process = audio_buffer[:block_size]
            audio_buffer = audio_buffer[block_size:]

            segments, _ = model.transcribe(
                audio_to_process,
                beam_size=5,
                language="en",
                task="transcribe"
            )
            text = " ".join([segment.text for segment in segments]).strip()
            if text:
                await result_queue.put(text)

def start_stream():
    global stream
    with stream_lock:
        if stream is None:
            stream = sd.InputStream(channels=1, samplerate=sample_rate, dtype='int16', callback=audio_callback)
            stream.start()
            print(">>> Listening started")

def stop_stream():
    global stream
    with stream_lock:
        if stream is not None:
            stream.stop()
            stream.close()
            stream = None
            print(">>> Listening stopped")

def on_press(key):
    global listening
    if key == keyboard.Key.space:
        listening = not listening
        if listening:
            start_stream()
        else:
            stop_stream()
    elif key == keyboard.Key.esc:
        print("Exiting...")
        stop_event.set()
        stop_stream()
        return False  # Stops the listener

async def result_consumer(result_queue: asyncio.Queue):
    while not stop_event.is_set():
        try:
            text = await asyncio.wait_for(result_queue.get(), timeout=1.0)
            print(f"Transcribed: {text}")
        except asyncio.TimeoutError:
            continue

async def main():
    print("Press SPACEBAR to toggle listening ON/OFF. Press ESC to exit.")
    result_queue = asyncio.Queue()

    transcriber_task = asyncio.create_task(transcribe_worker(result_queue))
    consumer_task = asyncio.create_task(result_consumer(result_queue))

    loop = asyncio.get_event_loop()
    listener_thread = threading.Thread(target=lambda: keyboard.Listener(on_press=on_press).run(), daemon=True)
    listener_thread.start()

    try:
        await asyncio.wait([transcriber_task, consumer_task])
    except asyncio.CancelledError:
        pass
    finally:
        stop_event.set()
        stop_stream()
        print("Program terminated.")

if __name__ == "__main__":
    asyncio.run(main())
