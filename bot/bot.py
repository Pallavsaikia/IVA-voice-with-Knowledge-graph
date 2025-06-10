import asyncio
import uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sockets.socket_manager import SocketManager
import os
import logging
from typing import Optional, Any

# Import the modules from your audio task handler
from task_manager.audio_task_manager import AudioTaskHandler 

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust origins as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("audio", exist_ok=True)


class IntegratedApp:
    """Integrated application class that manages the audio task handler"""
    
    def __init__(self):
        # Initialize your query engine here
        # You'll need to uncomment and adjust this based on your actual implementation
        try:
            from rag.neo4j import Neo4jQueryEngine
            Neo4jQueryEngine.setup_llm()
            self.query_engine = Neo4jQueryEngine()
        except ImportError:
            # Fallback for testing - replace with your actual query engine
            logger.warning("Neo4jQueryEngine not available, using mock query engine")
            self.query_engine = self._create_mock_query_engine()
        
        # Initialize the audio task handler
        self.audio_task_handler = AudioTaskHandler(self.query_engine)
    
    def _create_mock_query_engine(self):
        """Mock query engine for testing purposes"""
        class MockQueryEngine:
            def query(self, text):
                return f"Mock response to: {text}"
        return MockQueryEngine()
    
    async def startup(self):
        """Call this during app startup"""
        await self.audio_task_handler.preload_tts_cache()
        logger.info("[IntegratedApp] Startup complete")
    
    async def on_receive(self, from_bot, data, message_type, socket_manager):
        """Pass this to your SocketManager"""
        await self.audio_task_handler.on_receive(from_bot, data, message_type, socket_manager)
    
    async def on_send(self, message):
        """Your existing on_send implementation"""
        pass
    
    async def bot_join_call(self, call_id, bot_id):
        """Your updated bot_join_call function"""
        logger.info(f"[IntegratedApp] Bot {bot_id} joining call {call_id}")
        primaryBotManager = SocketManager(call_id=call_id, bot_id=bot_id)
        
        try:
            await primaryBotManager.connect(
                on_receive=self.on_receive, 
                on_send=self.on_send
            )
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            print(f"[BOT] Bot {bot_id} is stopping...")
            await self.audio_task_handler.cleanup_call(call_id)
            await primaryBotManager.disconnect_bot(bot_id)
            print(f"[BOT] Bot {bot_id} has stopped.")
        except Exception as e:
            print(f"[BOT] Error in bot_join_call for bot {bot_id}: {e}")
            await self.audio_task_handler.cleanup_call(call_id)


# Create global instance of the integrated app
integrated_app = IntegratedApp()

# Stores: {bot_id: {"task": asyncio.Task, "manager": SocketManager}}
active_bots = {}

# Updated callback functions that use the integrated app
async def on_receive(from_bot, data, message_type, socket_manager: SocketManager):
    """Updated on_receive that uses the audio task handler"""
    await integrated_app.on_receive(from_bot, data, message_type, socket_manager)

async def on_send(message):
    """Your existing on_send implementation"""
    await integrated_app.on_send(message)

async def bot_join_call(call_id, bot_id):
    """Updated bot_join_call that uses the integrated app"""
    await integrated_app.bot_join_call(call_id, bot_id)

@app.on_event("startup")
async def startup_event():
    """Initialize the integrated app on startup"""
    await integrated_app.startup()

@app.post("/join")
async def join_call(request: Request):
    data = await request.json()
    call_id = data.get("room_id")
    print(f"[JOIN] Received call_id: {call_id}")
    
    if not call_id:
        return {"error": "Missing call_id"}
    
    bot_id = f"bot_{uuid.uuid4().hex[:8]}"
    
    if bot_id in active_bots:
        return {"status": "bot already active", "bot_id": bot_id}
    
    task = asyncio.create_task(bot_join_call(call_id, bot_id))
    active_bots[bot_id] = {"task": task, "call_id": call_id}
    
    logger.info(f"[JOIN] Bot {bot_id} joining call {call_id}")
    return {"status": "bot joining", "bot_id": bot_id, "call_id": call_id}

@app.post("/leave")
async def leave_call(request: Request):
    data = await request.json()
    bot_id = data.get("bot_id")
    
    if not bot_id:
        return {"error": "Missing bot_id"}
    
    if bot_id in active_bots:
        task = active_bots[bot_id]["task"]
        call_id = active_bots[bot_id]["call_id"]
        
        # Cancel the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Clean up resources
        await integrated_app.audio_task_handler.cleanup_call(call_id)
        
        del active_bots[bot_id]
        logger.info(f"[LEAVE] Bot {bot_id} disconnected from call {call_id}")
        return {"status": "bot left"}
    
    return {"status": "bot not found"}

@app.get("/status")
async def get_status():
    """Get status of active bots"""
    return {
        "active_bots": len(active_bots),
        "bots": {
            bot_id: {
                "call_id": info["call_id"],
                "task_done": info["task"].done()
            }
            for bot_id, info in active_bots.items()
        }
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "audio-bot-service"}