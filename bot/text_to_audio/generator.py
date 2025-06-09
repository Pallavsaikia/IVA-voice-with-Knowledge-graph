from gtts import gTTS
import io

class GTTSService:
    def __init__(self, lang="en"):
        self.lang = lang

    def text_to_audio_bytes(self, text: str) -> bytes:
        tts = gTTS(text=text, lang=self.lang)
        buffer = io.BytesIO()
        tts.write_to_fp(buffer)
        return buffer.getvalue()
    
import os
import hashlib

class TTSCache:
    def __init__(self, tts_service, cache_dir="tts_cache"):
        self.tts_service = tts_service
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _hash_text(self, text: str) -> str:
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def get_audio_bytes(self, text: str) -> bytes:
        key = self._hash_text(text)
        cache_path = os.path.join(self.cache_dir, f"{key}.wav")  # or mp3 based on your tts

        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                audio_bytes = f.read()
            print(f"Loaded audio from cache for: {text}")
        else:
            audio_bytes = self.tts_service.text_to_audio_bytes(text)
            with open(cache_path, "wb") as f:
                f.write(audio_bytes)
            print(f"Cached new audio for: {text}")

        return audio_bytes