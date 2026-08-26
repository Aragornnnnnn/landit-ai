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
    onset으로 넘긴다("hiking" → "hik" + "ing"). 묵음 e는 앞 음절에 흡수한다.
    """
    if syllable_count <= 0:
        return None
    if syllable_count == 1:
        return [word]

    nuclei = _nuclei(word)
    if len(nuclei) != syllable_count:
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


def _nuclei(word: str) -> list[tuple[int, int]]:
    """음절 핵이 되는 모음 글자 덩어리의 (시작, 끝) 위치."""
    clusters = [(match.start(), match.end()) for match in _VOWEL_CLUSTER.finditer(word)]
    if len(clusters) <= 1:
        return clusters

    last_start, last_end = clusters[-1]
    is_final_e = (
        last_end == len(word)
        and word[last_start:last_end].lower() == "e"
        and last_start > 0
        and word[last_start - 1].lower() not in _VOWEL_LETTERS
    )
    # 묵음 e("like", "available")는 독립 음절이 아니므로 핵에서 뺀다
    return clusters[:-1] if is_final_e else clusters
