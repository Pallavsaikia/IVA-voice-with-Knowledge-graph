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
    
    def pick_random_greeting(self) -> str:
        pause_text = random.choice(self.pause_text)
        logger.info(f"[Pause Text] Selected Pause Text: {pause_text}")
        return pause_text
