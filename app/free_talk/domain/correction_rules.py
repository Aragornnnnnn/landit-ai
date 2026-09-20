# 프리톡 턴 교정 결과를 원문과 대조하는 순수 규칙 모듈
import re
from difflib import SequenceMatcher


# 여는 둥근 따옴표와 큰따옴표는 단어 글자가 아니다. 닫는 작은따옴표(’)는 아포스트로피와 같은 글자라 떼지 않는다.
_EDGE_PUNCTUATION = ".,!?;:\"()“”‘"
# iOS 키보드는 기본으로 둥근 아포스트로피(’)를 넣고, 모델은 옮겨 적으며 곧은 것(')으로 바꾸기도 한다.
_APOSTROPHES = "'’"


def comparable_word(word: str) -> str:
    """단어끼리 같은지 볼 때 쓰는 모양. 대소문자, 아포스트로피 모양, 양끝 문장부호를 무시한다."""
    return word.strip(_EDGE_PUNCTUATION).lower().replace("’", "'")


def _word_pattern(word: str) -> str:
    """단어 하나를 정규식으로 바꾼다. 곧은 아포스트로피와 둥근 아포스트로피는 같은 글자로 본다."""
    return re.escape(word).replace("’", "'").replace("'", f"[{_APOSTROPHES}]")


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
    pattern = re.compile(r"\s+".join(_word_pattern(word) for word in words), re.IGNORECASE)
    match = pattern.search(content)
    if match is None:
        return None
    return content[match.start() : match.end()]


def _span_matches(sentence: str, candidate: str) -> list[re.Match[str]]:
    words = candidate.split()
    if not words:
        return []
    # don't 안의 don, well-known 안의 well처럼 단어 일부만 걸리지 않도록 아포스트로피(곧은 것과 둥근 것)와
    # 하이픈도 단어 글자로 본다
    source = (
        rf"(?<![\w{_APOSTROPHES}-])"
        + r"\s+".join(_word_pattern(word) for word in words)
        + rf"(?![\w{_APOSTROPHES}-])"
    )
    # 화면은 구절 문자열로 위치를 다시 찾는다. They와 they처럼 대소문자가 다른 단어는 서로 다른 구절이므로,
    # 대소문자까지 같은 자리가 하나면 그 자리로 본다. 없을 때만 대소문자를 무시한다(모델이 바꿔 적은 경우).
    exact = list(re.finditer(source, sentence))
    if exact:
        return exact
    return list(re.finditer(source, sentence, re.IGNORECASE))


def span_rejection(sentence: str, candidate: str) -> str | None:
    """강조 구절을 쓸 수 없는 이유를 돌려준다. 쓸 수 있으면 None이다.

    화면은 구절 문자열로 위치를 다시 찾으므로, 단어 경계 기준으로 문장 안에 정확히 한 번 나와야 한다.
    """
    if not candidate.strip():
        return "blank"
    matches = _span_matches(sentence, candidate)
    if not matches:
        return "not_found"
    if len(matches) > 1:
        return "ambiguous"
    return None


def locate_span(sentence: str, candidate: str) -> str | None:
    """강조 구절을 문장 원문 그대로의 조각으로 돌려준다. 쓸 수 없으면 None이다."""
    span_range = span_range_in(sentence, candidate)
    if span_range is None:
        return None
    return sentence[span_range[0] : span_range[1]]


def span_range_in(sentence: str, candidate: str) -> tuple[int, int] | None:
    """강조 구절이 문장 안에서 차지하는 [시작, 끝) 위치. 정확히 한 번 나올 때만 돌려준다."""
    matches = _span_matches(sentence, candidate)
    if len(matches) != 1:
        return None
    return matches[0].start(), matches[0].end()


def word_after_insertion(original: str, better: str) -> str | None:
    """단어를 채워 넣기만 한 교정에서 빈자리 바로 뒤 단어를 원문 조각으로 돌려준다.

    바뀐 곳이 삽입 하나뿐이고 그 뒤 단어가 문장에서 유일할 때만 돌려준다. 빠진 단어에는 짚을 글자가
    없으므로, 그 자리를 가리킬 때 이 단어를 쓴다.
    """
    original_words = [word.strip(_EDGE_PUNCTUATION) for word in original.split()]
    # 모델이 옮겨 적으며 아포스트로피 모양을 바꾼 것(don’t → don't)은 바뀐 곳으로 치지 않는다
    changes = [
        opcode
        for opcode in SequenceMatcher(
            None,
            [comparable_word(word) for word in original.split()],
            [comparable_word(word) for word in better.split()],
            autojunk=False,
        ).get_opcodes()
        if opcode[0] != "equal"
    ]
    if len(changes) != 1 or changes[0][0] != "insert" or changes[0][1] >= len(original_words):
        return None
    return locate_span(original, original_words[changes[0][1]])


def is_effective_correction(original: str, better: str) -> bool:
    """원문과 교정문이 실제로 다를 때만 교정으로 인정한다."""
    return original.strip() != better.strip()


_WORD_PATTERN = re.compile(rf"[A-Za-z0-9{_APOSTROPHES}]+")
_INDEFINITE_ARTICLES = {"a", "an"}


def is_only_definite_article_swap(original: str, better: str) -> bool:
    """바뀐 것이 a/an을 the로 바꾼 것뿐인지 본다.

    듣는 사람이 이미 아는 대상이라는 근거(장기기억)가 없으면 이 교정은 추측이다.
    """
    original_words = [comparable_word(word) for word in _WORD_PATTERN.findall(original)]
    better_words = [comparable_word(word) for word in _WORD_PATTERN.findall(better)]
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
