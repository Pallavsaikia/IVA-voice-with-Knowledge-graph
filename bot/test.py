import asyncio
from sockets.socket_manager import SocketManager

async def on_receive(message):
    print(f"[Received] {message}")

async def on_send(message):
    pass

async def main():
    call_id = "testcall"
    manager = SocketManager(call_id)

    # Connect two bots to the same call/room
    await manager.connect_bot("bot_alpha", on_receive=on_receive, on_send=on_send)
    await manager.connect_bot("bot_bravo", on_receive=on_receive, on_send=on_send)

    # Send messages from bot_alpha
    await manager.send_message("bot_alpha", msg_type="bot_message", data={"text": "Hello from Alpha!"}, on_send=on_send)

    # Simulate wait for messages
    # await asyncio.sleep(10)

    # # Disconnect all bots cleanly
    # await manager.disconnect_all()

asyncio.run(main())
