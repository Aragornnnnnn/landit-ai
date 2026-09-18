# 프리톡 턴 교정 결과를 원문과 대조하는 순수 규칙 모듈
import re


def locate_original_sentence(content: str, candidate: str) -> str | None:
    """모델이 고른 문장을 제출 원문 안에서 찾아 원문 그대로의 조각을 돌려준다.

    대소문자와 공백 차이는 허용하되 반환값은 항상 원문의 정확한 부분 문자열이다.
    찾지 못하면 None을 돌려주고, 호출부가 교정을 버릴지 결정한다.
    """
    stripped = candidate.strip()
    if not stripped:
        return None
    if stripped in content:
        return stripped
    words = stripped.split()
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words), re.IGNORECASE)
    match = pattern.search(content)
    if match is None:
        return None
    return content[match.start() : match.end()]


def is_effective_correction(original: str, better: str) -> bool:
    """원문과 교정문이 실제로 다를 때만 교정으로 인정한다."""
    return original.strip() != better.strip()
