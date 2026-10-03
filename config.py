from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env")

    # Required
    nvidia_api_key: str
    github_token: str
    github_webhook_secret: str

    # App
    api_key: str = ""
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    frontend_url: str = "http://localhost:5173"

    # NVIDIA NIM
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3-super-120b-a12b"
    nvidia_model_fast: str = "nvidia/nemotron-3.5-lightning-30b-a3b"

    # Generation
    max_tokens: int = 1200
    temperature: float = 0.1

    # Timeouts
    llm_timeout_seconds: float = 75.0
    llm_fast_timeout_seconds: float = 45.0

    # NVIDIA options
    nvidia_enable_thinking: bool = False
    nvidia_use_json_mode: bool = False

    # Concurrency
    max_concurrent_llm_calls: int = 1

    # Review limits
    max_diff_chars: int = 20000
    max_findings_per_agent: int = 25


_settings = None


def get_settings() -> Settings:
    global _settings

    if _settings is None:
        _settings = Settings()

    return _settings