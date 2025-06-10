import asyncio
import websockets
import json
import time

class SocketManager:
    def __init__(self):
        # Store websockets by (call_id, bot_id)
        self.active_connections = {}
        # Store receive tasks
        self.receive_tasks = {}

    async def send_message(self, call_id, bot_id, msg_type=None, data=None, to_clients=None, raw_audio=None, on_send=None):
        websocket = self.active_connections.get((call_id, bot_id))
        if websocket is None:
            raise Exception(f"No active connection for call {call_id} and bot {bot_id}")

        if raw_audio is not None:
            # Send raw bytes
            await websocket.send(raw_audio)
            if on_send:
                # Pass raw audio info (you can customize the dict as you want)
                await on_send({"type": "audio", "bytes_sent": len(raw_audio), "call_id": call_id, "bot_id": bot_id})
        else:
            # Send JSON message
            message = {
                "type": msg_type,
                "data": data or {},
                "to": to_clients or [],
                "timestamp": int(time.time() * 1000)
            }
            message_json = json.dumps(message)
            await websocket.send(message_json)
            if on_send:
                # Pass the actual dict message (not JSON string) so easier to inspect
                await on_send({"sent_message": message, "call_id": call_id, "bot_id": bot_id})

    async def _receive_loop(self, call_id, bot_id, websocket, on_receive):
        try:
            async for message in websocket:
                # websockets delivers str or bytes depending on what server sent
                # Try to parse JSON if str, else pass raw bytes directly
                if isinstance(message, bytes):
                    # raw binary data received (audio etc)
                    if on_receive:
                        await on_receive({"type": "audio", "bytes_received": len(message), "data": message, "call_id": call_id, "bot_id": bot_id})
                else:
                    # Text message, try JSON parse
                    try:
                        data = json.loads(message)
                    except Exception:
                        data = message
                    if on_receive:
                        await on_receive({"type": "json", "data": data, "call_id": call_id, "bot_id": bot_id})
        except websockets.ConnectionClosed:
            print(f"[SocketManager] Connection closed for bot {bot_id} in call {call_id}")
        except Exception as e:
            print(f"[SocketManager] Receive loop error for bot {bot_id} in call {call_id}: {e}")
        finally:
            self.active_connections.pop((call_id, bot_id), None)
            self.receive_tasks.pop((call_id, bot_id), None)
            print(f"[SocketManager] Bot {bot_id} disconnected from call {call_id}")

    async def start_bot(self, call_id, bot_id, on_receive=None, on_send=None):
        uri = f"ws://localhost:8080/ws?room={call_id}&clientId={bot_id}&type=agent"
        print(f"[SocketManager] Connecting bot {bot_id} to {uri}")
        websocket = await websockets.connect(uri)
        self.active_connections[(call_id, bot_id)] = websocket
        print(f"[SocketManager] Bot {bot_id} connected to call {call_id}")

        # Send initial message
        await self.send_message(
            call_id, bot_id, msg_type="bot_message", data={"text": "Hi, I'm connected and ready."}, on_send=on_send
        )

        # Start receive loop in background task
        task = asyncio.create_task(self._receive_loop(call_id, bot_id, websocket, on_receive))
        self.receive_tasks[(call_id, bot_id)] = task

    async def stop_bot(self, call_id, bot_id):
        websocket = self.active_connections.get((call_id, bot_id))
        if websocket:
            await websocket.close()
            print(f"[SocketManager] Closed connection for bot {bot_id} in call {call_id}")

        task = self.receive_tasks.get((call_id, bot_id))
        if task:
            task.cancel()
