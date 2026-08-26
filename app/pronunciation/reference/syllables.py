# 철자를 발음 음절 수에 맞춰 나누는 모듈
#
# 음소를 글자로 옮기면 "like"가 "leyek"처럼 읽을 수 없는 표기가 된다. 그래서 음소는
# 음절 수와 강세 위치를 정하는 데만 쓰고, 화면에 보이는 것은 원래 철자를 쪼갠 것으로 한다.
# LAN-209에서 사람이 만든 기준(poc_manifest_tts.json)도 "hik·ing", "like"처럼 철자 기반이다.
#
# 하이픈 사전(pyphen)은 음절 사전이 아니라 줄바꿈 사전이라 3,000단어 표본에서 38.5%가
# CMUdict 모음 수와 어긋났다(barter를 1음절, overlook을 2음절로 본다). 그래서 쓰지 않는다.
import re

_VOWEL_LETTERS = "aeiouy"
# 모음 글자 덩어리. 뒤이어 오는 자음은 별도로 붙인다.
_VOWEL_CLUSTER = re.compile(f"[{_VOWEL_LETTERS}]+", re.IGNORECASE)


def split_syllables(word: str, syllable_count: int) -> list[str] | None:
    """철자를 syllable_count개로 나눈다. 나눌 수 없으면 None을 반환한다.

    모음 글자 덩어리를 음절 핵으로 보고, 핵 사이의 자음은 마지막 하나만 다음 음절의
    onset으로 넘긴다("hiking" → "hik" + "ing"). 묵음 e 흡수, -es/-ed의 e 흡수,
    -ing 앞 모음 분리("doing" → "do"+"ing") 등 여러 후보를 만들어 발음 음절 수와
    맞는 것을 고른다.
    """
    if syllable_count <= 0:
        return None
    if syllable_count == 1:
        return [word]

    nuclei = None
    for candidate in _nuclei_candidates(word):
        if len(candidate) == syllable_count:
            nuclei = candidate
            break
    if nuclei is None:
        return None

    boundaries = []
    for current, following in zip(nuclei, nuclei[1:]):
        consonant_start = current[1]
        consonant_end = following[0]
        boundary = (
            consonant_end - 1
            if consonant_end - consonant_start >= 1
            else consonant_start
        )
        # 한 소리를 내는 자음 이중자(th, ch, sh…)는 쪼개지 않는다.
        # "nothing"을 "not·hing"으로 끊으면 th가 갈라져 읽을 수 없다.
        if _splits_digraph(word, boundary):
            boundary -= 1
        boundaries.append(max(boundary, consonant_start))

    pieces = []
    start = 0
    for boundary in boundaries:
        pieces.append(word[start:boundary])
        start = boundary
    pieces.append(word[start:])
    return pieces if all(pieces) else None


# 한 소리를 내므로 음절 경계로 쪼개면 안 되는 자음 이중자
_DIGRAPHS = frozenset({"th", "ch", "sh", "ph", "wh", "gh", "ng", "ck", "qu"})


def _splits_digraph(word: str, boundary: int) -> bool:
    if boundary <= 0 or boundary >= len(word):
        return False
    return word[boundary - 1 : boundary + 1].lower() in _DIGRAPHS


def _nuclei_candidates(word: str) -> list[list[tuple[int, int]]]:
    """가능한 음절 핵(모음 덩어리) 구성을 그럴듯한 순서로 나열한다.

    영어 철자는 발음 음절과 1:1이 아니므로("maybe"의 끝 e는 소리 나고 "like"의 e는
    묵음) 변형을 만들어 발음 음절 수와 대조해 고른다.
    """
    raw = [(match.start(), match.end()) for match in _VOWEL_CLUSTER.finditer(word)]
    candidates = [raw]

    # 묵음 e: "like", "available"의 어말 e
    last = raw[-1] if raw else None
    if (
        len(raw) > 1
        and last[1] == len(word)
        and word[last[0]:last[1]].lower() == "e"
        and word[last[0] - 1].lower() not in _VOWEL_LETTERS
    ):
        candidates.append(raw[:-1])

    # -es/-ed의 묵음 e: "survives", "minutes", "turned"
    if (
        len(raw) > 1
        and last is not None
        and last[1] == len(word) - 1
        and word[last[0]:last[1]].lower() == "e"
        and word[-1].lower() in "sd"
        and word[last[0] - 1].lower() not in _VOWEL_LETTERS
    ):
        candidates.append(raw[:-1])

    # -ing 앞 모음 분리: "doing"(oi), "staying"(ayi)처럼 ing의 i가
    # 앞 모음과 한 덩어리로 붙은 경우 ing를 독립 음절로 떼어낸다
    if word.lower().endswith("ing") and len(word) > 3:
        ing_vowel = len(word) - 3
        for base in list(candidates):
            for index, (start, end) in enumerate(base):
                if start < ing_vowel < end:
                    split = (
                        base[:index]
                        + [(start, ing_vowel), (ing_vowel, end)]
                        + base[index + 1:]
                    )
                    candidates.append(split)
    return candidates
