import asyncio
import edge_tts
import io
import logging
from typing import Optional, Dict, Any
import random

logger = logging.getLogger(__name__)

class EdgeTTSService:
    def __init__(self, 
                 voice: str = "en-US-AriaNeural",
                 rate: str = "+0%",
                 pitch: str = "+0Hz"):
        
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        
        # Cache for audio bytes
        self.audio_cache: Dict[str, bytes] = {}
        
        # Wait messages that can be pre-cached
        self.wait_messages = [
            "Just a sec.",
            "Uhmm give me a sec",
            "Please be on line",
            "Let me think about that",
            "One moment please",
            "Processing your request"
        ]
        
        logger.info(f"[EdgeTTS] Initialized with voice: {voice}")
    
    async def text_to_audio_bytes(self, text: str, use_cache: bool = True) -> bytes:
        """
        Convert text to audio bytes using Edge TTS
        
        Args:
            text: Text to convert to speech
            use_cache: Whether to use cached audio for repeated text
            
        Returns:
            Audio bytes in the format suitable for WebSocket transmission
        """
        if not text or not text.strip():
            logger.warning("[EdgeTTS] Empty text provided for TTS")
            return b''
        
        text = text.strip()
        
        # Check cache first
        if use_cache and text in self.audio_cache:
            logger.debug(f"[EdgeTTS] Using cached audio for: '{text[:50]}...'")
            return self.audio_cache[text]
        
        try:
            # Create TTS communication
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                pitch=self.pitch
            )
            
            # Generate audio
            audio_bytes = b''
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]
            
            if not audio_bytes:
                logger.warning(f"[EdgeTTS] No audio generated for text: '{text[:50]}...'")
                return b''
            
            # Cache the result if requested
            if use_cache:
                self.audio_cache[text] = audio_bytes
                logger.debug(f"[EdgeTTS] Cached audio for: '{text[:50]}...'")
            
            logger.info(f"[EdgeTTS] Generated {len(audio_bytes)} bytes for: '{text[:50]}...'")
            return audio_bytes
            
        except Exception as e:
            logger.error(f"[EdgeTTS] Error generating TTS for '{text[:50]}...': {e}")
            return b''
    
    async def get_wait_message_audio(self) -> tuple[str, bytes]:
        """
        Get a random wait message and its corresponding audio
        
        Returns:
            (wait_text, audio_bytes): Tuple of the wait message text and audio bytes
        """
        wait_text = random.choice(self.wait_messages)
        audio_bytes = await self.text_to_audio_bytes(wait_text, use_cache=True)
        return wait_text, audio_bytes
    
    async def preload_wait_messages(self):
        """Preload all wait messages into cache"""
        logger.info("[EdgeTTS] Preloading wait messages...")
        
        for message in self.wait_messages:
            await self.text_to_audio_bytes(message, use_cache=True)
        
        logger.info(f"[EdgeTTS] Preloaded {len(self.wait_messages)} wait messages")
    
    def clear_cache(self):
        """Clear the audio cache"""
        cache_size = len(self.audio_cache)
        self.audio_cache.clear()
        logger.info(f"[EdgeTTS] Cleared audio cache ({cache_size} items)")
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the current cache"""
        return {
            "cache_size": len(self.audio_cache),
            "cached_texts": list(self.audio_cache.keys()),
            "total_bytes": sum(len(audio) for audio in self.audio_cache.values())
        }
    
    def set_voice_settings(self, voice: Optional[str] = None, 
                          rate: Optional[str] = None, 
                          pitch: Optional[str] = None):
        """Update voice settings"""
        if voice:
            self.voice = voice
        if rate:
            self.rate = rate
        if pitch:
            self.pitch = pitch
        
        logger.info(f"[EdgeTTS] Updated settings - Voice: {self.voice}, Rate: {self.rate}, Pitch: {self.pitch}")
    
    @staticmethod
    async def get_available_voices():
        """Get list of available voices"""
        try:
            voices = await edge_tts.list_voices()
            return voices
        except Exception as e:
            logger.error(f"[EdgeTTS] Error getting available voices: {e}")
            return []