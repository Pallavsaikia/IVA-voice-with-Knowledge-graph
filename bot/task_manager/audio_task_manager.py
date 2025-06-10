import asyncio
import json
import logging
import random
from typing import Optional, Any

# Import the modules we created
from task_manager.task_manager import TaskManager
from audio.audio_processor import AudioProcessor
from transcription.transcriber import Transcriber
from text_to_audio.edge_tts import EdgeTTSService
from sockets.socket_manager import SocketManager
logger = logging.getLogger(__name__)

class AudioTaskHandler:
    """Handles audio processing tasks that integrate with your existing SocketManager"""
    
    def __init__(self, query_engine):
        self.query_engine = query_engine
        
        # Initialize components
        self.task_manager = TaskManager()
        self.audio_processor = AudioProcessor()
        self.transcriber = Transcriber()
        self.tts_service = EdgeTTSService()
        
        logger.info("[AudioTaskHandler] Initialized all components")
    
    async def on_receive(self, from_bot, data, message_type, socket_manager:SocketManager):
        """
        This is the callback function that gets passed to your existing SocketManager
        """
        try:
            call_id = socket_manager.call_id
            
            if message_type == "json":
                await self._handle_json_message(data, call_id, socket_manager)
            elif message_type == "audio":
                await self._handle_audio_message(data, call_id, socket_manager)
                
        except Exception as e:
            logger.error(f"[AudioTaskHandler] Error in on_receive for call {call_id}: {e}")
    
    async def _handle_json_message(self, data, call_id, socket_manager:SocketManager):
        """Handle JSON messages"""
        if isinstance(data, dict):
            message_type = data.get("type")
            
            if message_type == "client_joined":
                client_info = data.get("data", {})
                if client_info.get("clientType") == "user":
                    await socket_manager.send_message(
                        msg_type="bot_message",
                        data={"text": "Hello! I see you've joined the call. How can I assist you today?"}
                    )
            elif message_type == "client_left":
                client_info = data.get("data", {})
                if client_info.get("clientType") == "user":
                    logger.info(f"[AudioTaskHandler] User {client_info.get('clientId')} left call {call_id}")
    
    async def _handle_audio_message(self, audio_data, call_id, socket_manager):
        """Handle incoming audio data"""
        try:
            # Process audio chunk
            should_transcribe, buffer_copy = self.audio_processor.process_audio_chunk(
                call_id, audio_data
            )
            
            if should_transcribe and buffer_copy:
                # Cancel any existing transcription task and create a new one
                await self.task_manager.create_task(
                    call_id,
                    self._transcribe_and_respond_task(buffer_copy, call_id, socket_manager),
                    "audio_process"
                )
        
        except Exception as e:
            logger.error(f"[AudioTaskHandler] Error handling audio for call {call_id}: {e}")
    
    async def _transcribe_and_respond_task(self, audio_buffer, call_id, socket_manager:SocketManager):
        """Task for transcribing audio and generating response"""
        try:
            logger.info(f"[AudioTaskHandler] Starting transcription task for call {call_id}")
            
            # Resample audio
            audio_16k = self.audio_processor.resample_audio(audio_buffer)
            
            # Transcribe
            transcribed_text, is_empty = await self.transcriber.transcribe_audio(
                audio_16k, self.audio_processor.target_sample_rate
            )
            
            # Check if this is silence (empty transcription + low energy)
            is_silence = self.transcriber.is_silence_detected(
                transcribed_text, audio_16k, self.audio_processor.silence_threshold
            )
            
            if is_silence:
                logger.debug(f"[AudioTaskHandler] Detected silence for call {call_id}, skipping response")
                return
            
            if transcribed_text:
                logger.info(f"[AudioTaskHandler] Processing transcription for call {call_id}: {transcribed_text}")
                await socket_manager.send_message(
                    msg_type="cancel_audio"
                )
                # Send transcription to users
                await socket_manager.send_message(
                    msg_type="transcription", 
                    data={"text": transcribed_text}
                )
                
                # Send wait message
                wait_text, wait_audio = await self.tts_service.get_wait_message_audio()
                await socket_manager.send_message(
                    msg_type="bot_message", 
                    data={"text": wait_text}
                )
                
                # Send wait audio
                if wait_audio:
                    await socket_manager.websocket.send(wait_audio)
                
                # Get response from query engine
                response = self.query_engine.query(transcribed_text)
                logger.info(f"[AudioTaskHandler] Generated response for call {call_id}: {response}")
                
                # Send text response
                await socket_manager.send_message(
                    msg_type="bot_message", 
                    data={"text": str(response)}
                )
                
                # Generate and send TTS response
                tts_audio = await self.tts_service.text_to_audio_bytes(str(response))
                if tts_audio:
                    await socket_manager.websocket.send(tts_audio)
            
        except asyncio.CancelledError:
            logger.info(f"[AudioTaskHandler] Transcription task cancelled for call {call_id}")
            raise
        except Exception as e:
            logger.error(f"[AudioTaskHandler] Error in transcription task for call {call_id}: {e}")
            # Send error message
            await socket_manager.send_message(
                msg_type="bot_message",
                data={"text": "Sorry, I encountered an error processing your request."}
            )
        finally:
            # Mark processing as finished
            self.audio_processor.finish_processing(call_id)
    
    async def cleanup_call(self, call_id):
        """Clean up resources for a specific call"""
        try:
            # Cancel all tasks for this call
            await self.task_manager.cleanup_call(call_id)
            
            # Clean up audio processor state
            self.audio_processor.cleanup_call_state(call_id)
            
            logger.info(f"[AudioTaskHandler] Cleaned up resources for call {call_id}")
            
        except Exception as e:
            logger.error(f"[AudioTaskHandler] Error during cleanup for call {call_id}: {e}")
    
    async def preload_tts_cache(self):
        """Preload common TTS responses"""
        await self.tts_service.preload_wait_messages()
        logger.info("[AudioTaskHandler] TTS cache preloaded")


# Updated usage with your existing SocketManager
"""
Here's how to integrate with your existing code:

# In your main application file, create a global handler
audio_task_handler = AudioTaskHandler(query_engine=your_neo4j_query_engine)

# Preload TTS cache on startup
await audio_task_handler.preload_tts_cache()

# Modified on_receive function
async def on_receive(from_bot, data, message_type, socket_manager):
    await audio_task_handler.on_receive(from_bot, data, message_type, socket_manager)

# Modified on_send function (keep as is)
async def on_send(message):
    pass  # Your existing implementation

# In your bot_join_call function:
async def bot_join_call(call_id, bot_id):
    logger.info(f"[Received] {call_id}")
    primaryBotManager = SocketManager(call_id=call_id, bot_id=bot_id)
    
    try:
        await primaryBotManager.connect(on_receive=on_receive, on_send=on_send)
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print(f"[BOT] Bot {bot_id} is stopping...")
        
        # Clean up resources for this call
        await audio_task_handler.cleanup_call(call_id)
        
        await primaryBotManager.disconnect()
        print(f"[BOT] Bot {bot_id} has stopped.")
    except Exception as e:
        print(f"[BOT] Error in bot_join_call for bot {bot_id}: {e}")
        # Clean up on error too
        await audio_task_handler.cleanup_call(call_id)
"""

# Example: Complete integration in your FastAPI app
# class IntegratedApp:
#     def __init__(self):
#         # Initialize your existing components
#         from rag.neo4j import Neo4jQueryEngine
#         Neo4jQueryEngine.setup_llm()
#         self.query_engine = Neo4jQueryEngine()
        
#         # Initialize the audio task handler
#         self.audio_task_handler = AudioTaskHandler(self.query_engine)
    
#     async def startup(self):
#         """Call this during app startup"""
#         await self.audio_task_handler.preload_tts_cache()
    
#     async def on_receive(self, from_bot, data, message_type, socket_manager):
#         """Pass this to your SocketManager"""
#         await self.audio_task_handler.on_receive(from_bot, data, message_type, socket_manager)
    
#     async def on_send(self, message):
#         """Your existing on_send implementation"""
#         pass
    
#     async def bot_join_call(self, call_id, bot_id):
#         """Your updated bot_join_call function"""
#         logger.info(f"[Received] {call_id}")
#         primaryBotManager = SocketManager(call_id=call_id, bot_id=bot_id)
        
#         try:
#             await primaryBotManager.connect(
#                 on_receive=self.on_receive, 
#                 on_send=self.on_send
#             )
#             while True:
#                 await asyncio.sleep(1)
#         except asyncio.CancelledError:
#             print(f"[BOT] Bot {bot_id} is stopping...")
#             await self.audio_task_handler.cleanup_call(call_id)
#             await primaryBotManager.disconnect()
#             print(f"[BOT] Bot {bot_id} has stopped.")
#         except Exception as e:
#             print(f"[BOT] Error in bot_join_call for bot {bot_id}: {e}")
#             await self.audio_task_handler.cleanup_call(call_id)