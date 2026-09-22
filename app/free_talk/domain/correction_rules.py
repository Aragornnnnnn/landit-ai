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


_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")
_INDEFINITE_ARTICLES = {"a", "an"}


def is_only_definite_article_swap(original: str, better: str) -> bool:
    """바뀐 것이 a/an을 the로 바꾼 것뿐인지 본다.

    듣는 사람이 이미 아는 대상이라는 근거(장기기억)가 없으면 이 교정은 추측이다.
    """
    original_words = [word.lower() for word in _WORD_PATTERN.findall(original)]
    better_words = [word.lower() for word in _WORD_PATTERN.findall(better)]
    if len(original_words) != len(better_words):
        return False
    changed = [
        (before, after)
        for before, after in zip(original_words, better_words, strict=True)
        if before != after
    ]
    return bool(changed) and all(
        before in _INDEFINITE_ARTICLES and after == "the" for before, after in changed
    )


# 실측 후 조정할 초기값. 화면 태그 "{날짜} 스몰톡에서 말한 {라벨}"에 들어갈 짧은 명사구의 상한이다.
MEMORY_LABEL_MAX_LENGTH = 20
_LABEL_FORBIDDEN_CHARS = frozenset("\n\r!?.！？。")
# 날짜는 백엔드가 observedAt으로 붙인다. "다음 주 면접"처럼 숫자 없는 표현은 날짜 표기가 아니다.
_LABEL_DATE_PATTERN = re.compile(
    r"\d{4}\s*-\s*\d{1,2}\s*-\s*\d{1,2}|\d{1,2}\s*/\s*\d{1,2}|\d+\s*[년월일]"
)


def memory_label_rejection(label: str) -> str | None:
    """화면용 기억 라벨을 쓸 수 없는 이유를 돌려준다. 쓸 수 있으면 None이다."""
    stripped = label.strip()
    if not stripped:
        return "blank"
    if len(stripped) > MEMORY_LABEL_MAX_LENGTH:
        return "too_long"
    if any(char in _LABEL_FORBIDDEN_CHARS for char in stripped):
        return "invalid_chars"
    if _LABEL_DATE_PATTERN.search(stripped):
        return "contains_date"
    return None
