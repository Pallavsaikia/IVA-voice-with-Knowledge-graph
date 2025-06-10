import asyncio
import logging
from typing import Dict, Optional, Callable, Any

logger = logging.getLogger(__name__)

class TaskManager:
    def __init__(self):
        # Store tasks per call_id: {call_id: {task_name: asyncio.Task}}
        self.active_tasks: Dict[str, Dict[str, asyncio.Task]] = {}
        self.task_locks: Dict[str, asyncio.Lock] = {}
    
    def get_lock(self, call_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific call_id"""
        if call_id not in self.task_locks:
            self.task_locks[call_id] = asyncio.Lock()
        return self.task_locks[call_id]
    
    async def cancel_task(self, call_id: str, task_name: str = "audio_process") -> bool:
        """Cancel a specific task for a call_id"""
        async with self.get_lock(call_id):
            if call_id in self.active_tasks and task_name in self.active_tasks[call_id]:
                task = self.active_tasks[call_id][task_name]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        logger.info(f"[TaskManager] Cancelled task '{task_name}' for call {call_id}")
                    except Exception as e:
                        logger.error(f"[TaskManager] Error cancelling task: {e}")
                
                del self.active_tasks[call_id][task_name]
                if not self.active_tasks[call_id]:  # Remove call_id if no tasks left
                    del self.active_tasks[call_id]
                return True
        return False
    
    async def create_task(self, call_id: str, coro, task_name: str = "audio_process") -> Optional[asyncio.Task]:
        """Create a new task for a call_id, cancelling any existing task with the same name"""
        async with self.get_lock(call_id):
            # Cancel existing task if it exists
            if call_id in self.active_tasks and task_name in self.active_tasks[call_id]:
                existing_task = self.active_tasks[call_id][task_name]
                if not existing_task.done():
                    existing_task.cancel()
                    try:
                        await existing_task
                    except asyncio.CancelledError:
                        logger.info(f"[TaskManager] Cancelled existing task '{task_name}' for call {call_id}")
                    except Exception as e:
                        logger.error(f"[TaskManager] Error cancelling existing task: {e}")
            
            # Create new task
            if call_id not in self.active_tasks:
                self.active_tasks[call_id] = {}
            
            task = asyncio.create_task(coro)
            self.active_tasks[call_id][task_name] = task
            logger.info(f"[TaskManager] Created new task '{task_name}' for call {call_id}")
            return task
    
    async def cleanup_call(self, call_id: str):
        """Cancel all tasks for a specific call_id"""
        async with self.get_lock(call_id):
            if call_id in self.active_tasks:
                for task_name, task in self.active_tasks[call_id].items():
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            logger.info(f"[TaskManager] Cleaned up task '{task_name}' for call {call_id}")
                        except Exception as e:
                            logger.error(f"[TaskManager] Error cleaning up task: {e}")
                
                del self.active_tasks[call_id]
                logger.info(f"[TaskManager] Cleaned up all tasks for call {call_id}")
    
    def get_active_tasks(self, call_id: str) -> Dict[str, asyncio.Task]:
        """Get all active tasks for a call_id"""
        return self.active_tasks.get(call_id, {})
    
    def is_task_running(self, call_id: str, task_name: str = "audio_process") -> bool:
        """Check if a specific task is running for a call_id"""
        if call_id in self.active_tasks and task_name in self.active_tasks[call_id]:
            return not self.active_tasks[call_id][task_name].done()
        return False