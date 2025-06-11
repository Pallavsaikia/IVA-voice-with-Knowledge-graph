import asyncio
import json
import websockets
import numpy as np
from scipy.signal import resample_poly
import logging
from typing import Tuple, Optional, Callable
from audio.audio_processor import AudioProcessor
logger = logging.getLogger(__name__)

class SocketManager:
    def __init__(self, base_url:str,call_id: str, bot_id: str, audio_processor: Optional[AudioProcessor] = None):
        self.call_id = call_id
        self.bot_id = bot_id
        self.websocket = None
        self.receive_task = None
        self.base_url = base_url
        self.auto_disconnect_enabled = True  # Flag to enable/disable auto-disconnect
        # Initialize audio processor
        self.audio_processor = audio_processor or AudioProcessor()
        self.audio_processor.initialize_call_state(self.call_id)
        
        # Track pending on_receive tasks to allow cancellation
        self.pending_on_receive_tasks = set()
    
    async def connect(self, on_receive: Optional[Callable] = None, on_send: Optional[Callable] = None):
        print("Connecting...")
        uri = f"ws://{self.base_url}/ws?room={self.call_id}&clientId={self.bot_id}&type=agent"
        print(f"[SocketManager] Connecting bot {self.bot_id} to {uri}")
        
        self.websocket = await websockets.connect(uri)
        print(f"[SocketManager] Bot {self.bot_id} connected to call {self.call_id}")
        
        await self.send_message(
            msg_type="bot_message", 
            data={"text": "Hi, I'm connected and ready."}, 
            on_send=on_send
        )
        
        self.receive_task = asyncio.create_task(self._receive_loop(on_receive))
        print("Connection established")
    
    async def send_message(self, msg_type: Optional[str] = None, data: Optional[dict] = None, 
                          to_clients: Optional[list] = None, raw_audio: Optional[bytes] = None, 
                          on_send: Optional[Callable] = None):
        if self.websocket is None:
            raise Exception(f"No active connection for bot {self.bot_id}")
        
        if raw_audio is not None:
            await self.websocket.send(raw_audio)
            # if on_send:
            #     await on_send({
            #         "type": "audio",
            #         "bytes_sent": len(raw_audio),
            #         "call_id": self.call_id,
            #         "bot_id": self.bot_id,
            #     })
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
    
    def set_auto_disconnect(self, enabled: bool):
        """Enable or disable automatic disconnection when users leave"""
        self.auto_disconnect_enabled = enabled
        logger.info(f"[SocketManager] Auto-disconnect {'enabled' if enabled else 'disabled'} for bot {self.bot_id}")
    
    async def _cancel_pending_on_receive_tasks(self, exclude_current: bool = True):
        """Cancel all pending on_receive tasks"""
        if self.pending_on_receive_tasks:
            current_task = asyncio.current_task() if exclude_current else None
            
            # Filter out the current task if exclude_current is True
            tasks_to_cancel = {
                task for task in self.pending_on_receive_tasks 
                if not task.done() and (not exclude_current or task != current_task)
            }
            
            if tasks_to_cancel:
                logger.info(f"[SocketManager] Cancelling {len(tasks_to_cancel)} pending on_receive tasks")
                
                for task in tasks_to_cancel:
                    task.cancel()
                
                # Wait for all tasks to complete their cancellation
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
                
                # Remove cancelled tasks from the set
                self.pending_on_receive_tasks -= tasks_to_cancel
    
    async def cancel_other_on_receive_tasks(self):
        """Public method to cancel all other pending on_receive tasks from within an on_receive callback"""
        await self._cancel_pending_on_receive_tasks(exclude_current=True)
    
    async def _handle_client_left(self, message_data: dict):
        """Handle client_left messages and auto-disconnect if user leaves"""
        if not self.auto_disconnect_enabled:
            return
        
        client_type = message_data.get('data', {}).get('clientType')
        client_id = message_data.get('data', {}).get('clientId')
        
        if client_type == 'user':
            logger.info(f"[SocketManager] User {client_id} left the room. Auto-disconnecting bot {self.bot_id}")
            print(f"[SocketManager] User left room - automatically disconnecting bot {self.bot_id}")
            
            # Optionally send a goodbye message before disconnecting
            try:
                await self.send_message(
                    msg_type="bot_message",
                    data={"text": "User left the room. Disconnecting..."}
                )
            except Exception as e:
                logger.warning(f"[SocketManager] Could not send goodbye message: {e}")
            
            # Disconnect after a short delay to allow the message to be sent
            asyncio.create_task(self._delayed_disconnect(delay=1.0))
    
    async def _delayed_disconnect(self, delay: float = 1.0):
        """Disconnect after a delay"""
        await asyncio.sleep(delay)
        await self.disconnect()
    
    async def _safe_on_receive_call(self, on_receive: Callable, *args, **kwargs):
        """Wrapper for on_receive calls that handles cancellation gracefully"""
        try:
            await on_receive(*args, **kwargs)
        except asyncio.CancelledError:
            logger.debug(f"[SocketManager] on_receive task cancelled for bot {self.bot_id}")
            raise  # Re-raise to properly handle cancellation
        except Exception as e:
            logger.error(f"[SocketManager] Error in on_receive callback: {e}")
        finally:
            # Remove this task from the pending set when it completes
            current_task = asyncio.current_task()
            self.pending_on_receive_tasks.discard(current_task)
    
    async def _receive_loop(self, on_receive: Optional[Callable]):
        try:
            async for message in self.websocket:
                if isinstance(message, bytes):
                    # Process audio through AudioProcessor
                    should_process, processed_buffer = self.audio_processor.process_audio_chunk(
                        self.call_id, message
                    )
                    
                    if should_process and processed_buffer and on_receive:
                        logger.info(f"[SocketManager] Processing audio buffer of {len(processed_buffer)} bytes")
                        
                        # Cancel previous pending on_receive tasks before starting new one
                        await self._cancel_pending_on_receive_tasks(exclude_current=False)
                        
                        # Create a task to handle the processed audio
                        task = asyncio.create_task(self._handle_processed_audio(
                            on_receive, processed_buffer
                        ))
                        self.pending_on_receive_tasks.add(task)
                    
                    # Optionally, you can still call on_receive for raw audio chunks
                    # if you want to handle them differently
                    # if on_receive:
                    #     await on_receive(
                    #         from_bot=self.bot_id,
                    #         data=message,
                    #         message_type="audio_chunk",
                    #         socket_manager=self
                    #     )
                
                else:
                    # Handle JSON messages
                    try:
                        data = json.loads(message)
                    except Exception:
                        data = message
                    
                    print(f"[SocketManager] Received JSON message: {data}")
                    
                    # Handle client_left messages for auto-disconnect
                    if isinstance(data, dict) and data.get('type') == 'client_left':
                        await self._handle_client_left(data)
                    
                    if on_receive:
                        # Cancel previous pending on_receive tasks before starting new one
                        await self._cancel_pending_on_receive_tasks(exclude_current=False)
                        
                        # Create and track the new on_receive task
                        task = asyncio.create_task(self._safe_on_receive_call(
                            on_receive,
                            from_bot=self.bot_id,
                            data=data,
                            message_type="json",
                            socket_manager=self
                        ))
                        self.pending_on_receive_tasks.add(task)
        
        except websockets.ConnectionClosed:
            print(f"[SocketManager] Connection closed for bot {self.bot_id} in call {self.call_id}")
        except Exception as e:
            print(f"[SocketManager] Receive loop error: {e}")
            logger.error(f"[SocketManager] Receive loop error for bot {self.bot_id}: {e}")
        finally:
            # Cancel any remaining pending tasks
            await self._cancel_pending_on_receive_tasks(exclude_current=False)
            
            self.websocket = None
            if self.receive_task:
                self.receive_task.cancel()
            print(f"[SocketManager] Bot {self.bot_id} disconnected from call {self.call_id}")
    
    async def _handle_processed_audio(self, on_receive: Callable, processed_buffer: bytearray):
        """Handle processed audio buffer in a separate task"""
        try:
            # Convert buffer to numpy array for transcription/processing
            audio_array = self.audio_processor.resample_audio(processed_buffer)
            
            # Call the on_receive callback with processed audio using the safe wrapper
            await self._safe_on_receive_call(
                on_receive,
                from_bot=self.bot_id,
                data={
                    "audio_buffer": processed_buffer,
                    "audio_array": audio_array,
                    "sample_rate": self.audio_processor.target_sample_rate,
                    "duration_seconds": len(audio_array) / self.audio_processor.target_sample_rate
                },
                message_type="processed_audio",
                socket_manager=self
            )
        
        except asyncio.CancelledError:
            logger.debug(f"[SocketManager] Audio processing task cancelled for bot {self.bot_id}")
            raise  # Re-raise to properly handle cancellation
        except Exception as e:
            logger.error(f"[SocketManager] Error handling processed audio: {e}")
        finally:
            # Mark processing as finished
            self.audio_processor.finish_processing(self.call_id)
    
    async def disconnect(self):
        # Cancel all pending on_receive tasks before disconnecting
        await self._cancel_pending_on_receive_tasks(exclude_current=False)
        
        # Clean up audio processor state
        self.audio_processor.cleanup_call_state(self.call_id)
        
        if self.websocket:
            await self.websocket.close()
            print(f"[SocketManager] Closed connection for bot {self.bot_id} in call {self.call_id}")
        
        if self.receive_task:
            self.receive_task.cancel()
    
    def is_audio_processing(self) -> bool:
        """Check if audio is currently being processed"""
        return self.audio_processor.is_processing(self.call_id)
    
    def get_pending_tasks_count(self) -> int:
        """Get the number of pending on_receive tasks (useful for debugging)"""
        return len([task for task in self.pending_on_receive_tasks if not task.done()])