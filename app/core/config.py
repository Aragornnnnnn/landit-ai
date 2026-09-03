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
    # 판정 프로바이더 고정 (OpenRouter 태그, 쉼표 구분 우선순위. 빈 값 = 자동 라우팅).
    # LAN-389 실측: 같은 모델이라도 Vertex 서빙은 STRESS 검출이 죽는다 —
    # 자동 라우팅이 Vertex로 기울면 검출 소실이 드리프트처럼 나타난다.
    pronunciation_provider_order: str = "google-ai-studio"
    pronunciation_reasoning_effort: str = "low"
    pronunciation_llm_timeout_seconds: float = 15.0
    pronunciation_reference_download_timeout_seconds: float = 5.0
    # 분석 1회의 전체 wall-clock 예산. BE 타임아웃(20초)보다 먼저 반환하기 위한 상한이며
    # 단계별 타임아웃은 이 예산의 남은 시간과 min으로 묶인다.
    pronunciation_total_budget_seconds: float = 17.0
    # 참조 오디오를 받아올 수 있는 origin 목록 (쉼표 구분). SSRF 차단용 —
    # 기본값은 콘텐츠 CDN 하나뿐이라 http·내부 주소는 자동 거부된다.
    pronunciation_reference_allowed_origins: str = (
        "https://d19azau1un4t7r.cloudfront.net"
    )
    # 오류 단어 묘사(respelling·오류 구간·강세)를 별도 호출로 채운다.
    # 대조 판정 프롬프트에 직접 요구하면 오탐이 생겨 분리했다 (LAN-373 골든 셋 A/B).
    pronunciation_describe_errors: bool = True
    # 정렬용 wav2vec2 int8 ONNX 모델 경로. 비우면 저장소 루트의 models/ 기본 경로
    pronunciation_alignment_model_path: str | None = None
    message_feedback_model: str | None = None
    openrouter_review_model: str | None = None
    message_feedback_review_enabled: bool = True
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    otel_metrics_enabled: bool = False
    otel_service_name: str = "landit-ai"
    otel_exporter_otlp_endpoint: str | None = None
    otel_exporter_otlp_headers: SecretStr | None = None
