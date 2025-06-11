import random
import logging
from typing import List

logger = logging.getLogger(__name__)

class Greetings:
    def __init__(self, greetings: List[str] = None):
        self.greetings = greetings or [
            "Hello!How may i assist you today",
            "Greetings!How can i help you."
        ]
    
    def pick_random_greeting(self) -> str:
        greeting = random.choice(self.greetings)
        logger.info(f"[Greetings] Selected greeting: {greeting}")
        return greeting


class PauseText:
    def __init__(self, pause_text: List[str] = None):
        self.pause_text = pause_text or [
            "Give me a minute.",
            "Please hold on"
        ]
    
    def pick_random_pause(self) -> str:
        pause_text = random.choice(self.pause_text)
        logger.info(f"[Pause Text] Selected Pause Text: {pause_text}")
        return pause_text


class StopResponseText:
    def __init__(self, stop_text: List[str] = None):
        self.stop_text = stop_text or [
            "Ok!sure.Let me know what you need.",
            "Ok i am listening"
        ]
    
    def pick_random_stop_text(self) -> str:
        stop_text = random.choice(self.stop_text)
        logger.info(f"[Stop Text] Selected Stop Text: {stop_text}")
        return stop_text
