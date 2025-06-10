import asyncio
from sockets.socket_manager import SocketManager
from text_to_audio.edge_tts import EdgeTTSService
async def on_receive(message):
    print(f"[Received] {message}")

async def on_send(message):
    pass

async def main():
    EdgeTTSService

asyncio.run(main())
