from pydantic import BaseSettings

class Settings(BaseSettings):
    model_size: str = "base"
    device: str = "cpu"
    port: int = 8000

settings = Settings()
