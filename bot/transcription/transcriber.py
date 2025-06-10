import io
import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class Transcriber:
    def __init__(self, 
                 model_size: str = "base",
                 compute_type: str = "int8",
                 device: str = "cpu",
                 language: str = "en"):
        
        self.model_size = model_size
        self.compute_type = compute_type
        self.device = device
        self.language = language
        
        # Initialize the model
        try:
            self.model = WhisperModel(model_size, compute_type=compute_type, device=device)
            logger.info(f"[Transcriber] Initialized Whisper model: {model_size}")
        except Exception as e:
            logger.error(f"[Transcriber] Failed to initialize Whisper model: {e}")
            raise
    
    async def transcribe_audio(self, audio_data: np.ndarray, sample_rate: int = 16000) -> Tuple[str, bool]:
        """
        Transcribe audio data to text
        
        Returns:
            (transcribed_text, is_empty): Tuple of transcribed text and whether it's empty/silence
        """
        try:
            # Create WAV file in memory
            wav_io = io.BytesIO()
            sf.write(wav_io, audio_data, sample_rate, format='WAV')
            wav_io.seek(0)
            
            # Transcribe
            segments, info = self.model.transcribe(wav_io, language=self.language)
            
            # Extract text from segments
            text_parts = []
            for segment in segments:
                if segment.text.strip():  # Only add non-empty segments
                    text_parts.append(segment.text.strip())
            
            transcribed_text = " ".join(text_parts)
            is_empty = len(transcribed_text.strip()) == 0
            
            if transcribed_text:
                logger.info(f"[Transcriber] Transcription result: '{transcribed_text}'")
            else:
                logger.debug("[Transcriber] Transcription resulted in empty text")
            
            return transcribed_text, is_empty
            
        except Exception as e:
            logger.error(f"[Transcriber] Error during transcription: {e}")
            return "", True
    
    def is_silence_detected(self, transcribed_text: str, audio_data: np.ndarray, 
                          silence_threshold: float = 0.02) -> bool:
        """
        Determine if the audio represents silence based on transcription and audio energy
        
        Returns:
            True if silence is detected (empty transcription AND low audio energy)
        """
        # Check if transcription is empty
        text_is_empty = len(transcribed_text.strip()) == 0
        
        # Check audio energy
        max_energy = np.max(np.abs(audio_data))
        audio_is_silent = max_energy < silence_threshold
        
        is_silence = text_is_empty and audio_is_silent
        
        if is_silence:
            logger.debug("[Transcriber] Silence detected: empty transcription + low audio energy")
        
        return is_silence
    
    def get_model_info(self) -> dict:
        """Get information about the loaded model"""
        return {
            "model_size": self.model_size,
            "compute_type": self.compute_type,
            "device": self.device,
            "language": self.language
        }