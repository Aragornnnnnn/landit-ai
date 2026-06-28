# OpenAI SDK 클라이언트 생성을 담당하는 모듈
from openai import OpenAI

from app.core.config import Settings


def create_openai_client(settings: Settings | None = None) -> OpenAI:
    resolved_settings = settings or Settings()
    if resolved_settings.llm_provider.lower() != "openrouter":
        raise RuntimeError("LLM_PROVIDER must be set to openrouter.")

    if (
        resolved_settings.openrouter_api_key is None
        or not resolved_settings.openrouter_api_key.get_secret_value().strip()
    ):
        raise RuntimeError("OPENROUTER_API_KEY is required to create an OpenAI client.")

    return OpenAI(
        api_key=resolved_settings.openrouter_api_key.get_secret_value(),
        base_url=resolved_settings.openrouter_base_url,
    )
