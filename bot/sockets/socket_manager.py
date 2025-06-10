import asyncio
import json
import websockets

class SocketManager:
    def __init__(self, call_id, bot_id):
        self.call_id = call_id
        self.bot_id = bot_id
        self.websocket = None
        self.receive_task = None

    async def connect(self, on_receive=None, on_send=None):
        print("done")
        uri = f"ws://localhost:8080/ws?room={self.call_id}&clientId={self.bot_id}&type=agent"
        print(f"[SocketManager] Connecting bot {self.bot_id} to {uri}")
        self.websocket = await websockets.connect(uri)
        print(f"[SocketManager] Bot {self.bot_id} connected to call {self.call_id}")

        await self.send_message(msg_type="bot_message", data={"text": "Hi, I'm connected and ready."}, on_send=on_send)

        self.receive_task = asyncio.create_task(self._receive_loop(on_receive))
        print("done")

    async def send_message(self, msg_type=None, data=None, to_clients=None, raw_audio=None, on_send=None):
        if self.websocket is None:
            raise Exception(f"No active connection for bot {self.bot_id}")

        if raw_audio is not None:
            await self.websocket.send(raw_audio)
            if on_send:
                await on_send({
                    "type": "audio",
                    "bytes_sent": len(raw_audio),
                    "call_id": self.call_id,
                    "bot_id": self.bot_id,
                })
        else:
            message = {
                "type": msg_type,
                "data": data or {},
                "to": to_clients or [],
                "timestamp": int(asyncio.get_event_loop().time() * 1000),
            }
            message_json = json.dumps(message)
            await self.websocket.send(message_json)
            if on_send:
                await on_send({
                    "sent_message": message,
                    "call_id": self.call_id,
                    "bot_id": self.bot_id,
                })

    async def _receive_loop(self, on_receive):
        try:
            async for message in self.websocket:
                # print(f"[SocketManager] Message received for bot {self.bot_id}: {message}")

                if isinstance(message, bytes):
                    # print(f"[SocketManager] Received audio message of length {len(message)}")
                    if on_receive:
                        await on_receive(
                            from_bot=self.bot_id,
                            data=message,
                            message_type="audio",
                            socket_manager=self
                        )
                else:
                    try:
                        data = json.loads(message)
                    except Exception:
                        data = message
                    print(f"[SocketManager] Received JSON message: {data}")
                    if on_receive:
                        await on_receive(
                            from_bot=self.bot_id,
                            data=data,
                            message_type="json",
                            socket_manager=self
                        )
        except websockets.ConnectionClosed:
            print(f"[SocketManager] Connection closed for bot {self.bot_id} in call {self.call_id}")
        except Exception as e:
            print(f"[SocketManager] Receive loop error: {e}")
        finally:
            self.websocket = None
            if self.receive_task:
                self.receive_task.cancel()
            print(f"[SocketManager] Bot {self.bot_id} disconnected from call {self.call_id}")

    async def disconnect(self):
        if self.websocket:
            await self.websocket.close()
            print(f"[SocketManager] Closed connection for bot {self.bot_id} in call {self.call_id}")
        if self.receive_task:
            self.receive_task.cancel()

