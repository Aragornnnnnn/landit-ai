# 발음 LLM 호출의 공통 요청 옵션(OpenRouter 라우팅 포함)을 만드는 모듈
#
# LAN-389 실측: 같은 모델 슬러그(google/gemini-3.5-flash)라도 서빙 프로바이더에
# 따라 판정이 갈린다 — AI Studio는 STRESS 3/3 검출, Vertex는 0/3 미검출.
# OpenRouter 자동 라우팅이 Vertex로 기울면서 검출 소실이 드리프트처럼 나타났으므로
# 프로바이더 우선순위를 고정하고, 다운 시에만 폴백을 허용한다(가용성 우선).
# 폴백이 실제로 발동하면 판정 품질이 조용히 저하되므로 호출부에서 warning을 남긴다.
from app.core.config import Settings

# OpenRouter는 라우팅에 태그(google-ai-studio)를, 응답 provider 필드에는
# 표시명(Google AI Studio)을 쓴다 — 폴백 발동 감지용 대조 표.
_PROVIDER_DISPLAY_NAMES = {
    "google-ai-studio": "Google AI Studio",
    "google-vertex": "Google",
}


def provider_order(settings: Settings) -> list[str]:
    return [
        entry.strip()
        for entry in settings.pronunciation_provider_order.split(",")
        if entry.strip()
    ]


def llm_extra_body(settings: Settings) -> dict:
    extra: dict = {
        "reasoning": {"effort": settings.pronunciation_reasoning_effort}
    }
    order = provider_order(settings)
    if order:
        extra["provider"] = {"order": order, "allow_fallbacks": True}
    return extra


def preferred_provider_display(settings: Settings) -> str | None:
    order = provider_order(settings)
    if not order:
        return None
    return _PROVIDER_DISPLAY_NAMES.get(order[0])


def served_by_fallback(settings: Settings, response) -> str | None:
    """응답이 선호 프로바이더가 아닌 곳에서 서빙됐으면 그 표시명을 반환한다."""
    expected = preferred_provider_display(settings)
    served = (getattr(response, "model_extra", None) or {}).get("provider")
    if expected and served and served != expected:
        return served
    return None
