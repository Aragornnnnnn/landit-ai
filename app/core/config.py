# 환경변수를 Pydantic Settings 객체로 관리하는 모듈
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "landit-ai"
    app_env: str = "local"
    app_version: str = "local"
    log_level: str = "INFO"
    llm_provider: str = "openrouter"
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str | None = None
    pronunciation_model: str = "google/gemini-3.5-flash"
    pronunciation_reasoning_effort: str = "low"
    pronunciation_llm_timeout_seconds: float = 15.0
    pronunciation_reference_download_timeout_seconds: float = 5.0
    # 오류 단어 묘사(respelling·오류 구간·강세)를 별도 호출로 채운다.
    # 대조 판정 프롬프트에 직접 요구하면 오탐이 생겨 분리했다 (LAN-373 골든 셋 A/B).
    pronunciation_describe_errors: bool = True
    message_feedback_model: str | None = None
    openrouter_review_model: str | None = None
    message_feedback_review_enabled: bool = True
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    otel_metrics_enabled: bool = False
    otel_service_name: str = "landit-ai"
    otel_exporter_otlp_endpoint: str | None = None
    otel_exporter_otlp_headers: SecretStr | None = None
