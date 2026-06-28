# OpenAI SDK 클라이언트 생성을 담당하는 모듈
from openai import OpenAI

from app.core.config import Settings


def create_openai_client(settings: Settings | None = None) -> OpenAI:
    resolved_settings = settings or Settings()
    if resolved_settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required to create an OpenAI client.")

    return OpenAI(api_key=resolved_settings.openai_api_key.get_secret_value())
