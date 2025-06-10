import numpy as np
from scipy.signal import resample_poly
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class AudioProcessor:
    def __init__(self, 
                 original_sample_rate: int = 48000,
                 target_sample_rate: int = 16000,
                 silence_threshold: float = 0.02,
                 silence_duration_ms: int = 1500,
                 min_buffer_duration_s: float = 2.0):
        
        self.original_sample_rate = original_sample_rate
        self.target_sample_rate = target_sample_rate
        self.silence_threshold = silence_threshold
        self.silence_duration_ms = silence_duration_ms
        self.min_buffer_duration_s = min_buffer_duration_s
        
        # Resampling parameters
        self.up = target_sample_rate
        self.down = original_sample_rate
        
        # Audio parameters
        self.bytes_per_sample = 2  # int16
        self.channels = 1
        
        # Per-call state tracking
        self.call_states = {}
    
    def initialize_call_state(self, call_id: str):
        """Initialize audio processing state for a new call"""
        self.call_states[call_id] = {
            'audio_buffer': bytearray(),
            'silent_duration': 0.0,
            'is_processing': False
        }
        logger.info(f"[AudioProcessor] Initialized state for call {call_id}")
    
    def cleanup_call_state(self, call_id: str):
        """Clean up audio processing state for a call"""
        if call_id in self.call_states:
            del self.call_states[call_id]
            logger.info(f"[AudioProcessor] Cleaned up state for call {call_id}")
    
    def get_call_state(self, call_id: str) -> dict:
        """Get or create call state"""
        if call_id not in self.call_states:
            self.initialize_call_state(call_id)
        return self.call_states[call_id]
    
    def process_audio_chunk(self, call_id: str, audio_data: bytes) -> Tuple[bool, Optional[bytearray]]:
        """
        Process incoming audio chunk and determine if we should transcribe
        
        Returns:
            (should_transcribe, buffer_copy): Tuple indicating if transcription should happen
            and the audio buffer to transcribe
        """
        state = self.get_call_state(call_id)
        
        if state['is_processing']:
            logger.debug(f"[AudioProcessor] Skipping chunk for call {call_id} - already processing")
            return False, None
        
        # Add to buffer
        state['audio_buffer'].extend(audio_data)
        
        # Calculate chunk duration
        chunk_samples = len(audio_data) // (self.bytes_per_sample * self.channels)
        chunk_duration = chunk_samples / self.original_sample_rate
        
        # Convert to float and resample
        try:
            audio_int16 = np.frombuffer(audio_data, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0
            audio_16k = resample_poly(audio_float, self.up, self.down)
            
            # Calculate energy
            energy = np.sqrt(np.mean(audio_16k ** 2))
            
            # Update silence duration
            if energy < self.silence_threshold:
                state['silent_duration'] += chunk_duration
            else:
                state['silent_duration'] = 0.0
            
            # Check if we should process
            min_buffer_len = self.target_sample_rate * self.min_buffer_duration_s * 2  # 2 bytes per sample
            silence_threshold_s = self.silence_duration_ms / 1000.0
            
            if (state['silent_duration'] >= silence_threshold_s and 
                len(state['audio_buffer']) > min_buffer_len):
                
                # Check if buffer has meaningful audio
                audio_int16_full = np.frombuffer(state['audio_buffer'], dtype=np.int16)
                audio_float_full = audio_int16_full.astype(np.float32) / 32768.0
                audio_16k_full = resample_poly(audio_float_full, self.up, self.down)
                max_energy = np.max(np.abs(audio_16k_full))
                
                if max_energy < self.silence_threshold:
                    logger.debug(f"[AudioProcessor] Buffer contains only silence for call {call_id}")
                    # Reset state
                    state['audio_buffer'] = bytearray()
                    state['silent_duration'] = 0.0
                    return False, None
                else:
                    logger.info(f"[AudioProcessor] {state['silent_duration']:.2f}s silence detected for call {call_id}")
                    # Mark as processing and return buffer copy
                    state['is_processing'] = True
                    buffer_copy = bytearray(state['audio_buffer'])
                    state['audio_buffer'] = bytearray()
                    state['silent_duration'] = 0.0
                    return True, buffer_copy
            
            return False, None
            
        except Exception as e:
            logger.error(f"[AudioProcessor] Error processing audio chunk for call {call_id}: {e}")
            return False, None
    
    def finish_processing(self, call_id: str):
        """Mark processing as finished for a call"""
        state = self.get_call_state(call_id)
        state['is_processing'] = False
        logger.debug(f"[AudioProcessor] Finished processing for call {call_id}")
    
    def resample_audio(self, audio_buffer: bytearray) -> np.ndarray:
        """Convert audio buffer to 16kHz float array"""
        try:
            audio_int16 = np.frombuffer(audio_buffer, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0
            
            if self.up != self.down:
                audio_16k = resample_poly(audio_float, up=self.up, down=self.down)
            else:
                audio_16k = audio_float
                
            return audio_16k
        except Exception as e:
            logger.error(f"[AudioProcessor] Error resampling audio: {e}")
            raise
    
    def is_processing(self, call_id: str) -> bool:
        """Check if currently processing audio for a call"""
        state = self.get_call_state(call_id)
        return state['is_processing']