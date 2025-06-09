import numpy as np
from faster_whisper import WhisperModel

class TranscriptionSession:
    model = WhisperModel("base", compute_type="int8", device="cpu")
    audio_buffer = np.zeros((0,), dtype=np.float32)
    block_size = 16000 * 3  # 3 seconds of audio at 16kHz

    @staticmethod
    def feed_and_transcribe(chunk: bytes) -> str | None:
        # Convert bytes (int16 PCM) to float32 normalized audio
        audio_np = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        TranscriptionSession.audio_buffer = np.concatenate((TranscriptionSession.audio_buffer, audio_np))

        if len(TranscriptionSession.audio_buffer) >= TranscriptionSession.block_size:
            segment = TranscriptionSession.audio_buffer[:TranscriptionSession.block_size]
            TranscriptionSession.audio_buffer = TranscriptionSession.audio_buffer[TranscriptionSession.block_size:]
            
            segments, _ = TranscriptionSession.model.transcribe(segment, language="en", beam_size=5)
            text = " ".join([seg.text for seg in segments]).strip()
            return text or None
        
        return None

    @staticmethod
    def transcribe_full(audio_np: np.ndarray) -> str:
        # Transcribe entire numpy float32 audio array at once
        segments, _ = TranscriptionSession.model.transcribe(audio_np, language="en", beam_size=5)
        return " ".join([seg.text for seg in segments]).strip()
