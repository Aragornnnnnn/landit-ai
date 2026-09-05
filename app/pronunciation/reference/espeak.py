# espeak-ng로 EN_GB/EN_AU 발음(IPA)을 얻어 음절·강세·respelling을 만드는 모듈
#
# CMUdict는 American English 전용이라 영국·호주 locale은 espeak-ng를 쓴다.
# 사전 파일과 달리 어떤 단어든 발음을 만들 수 있고 en-gb 품질은 억양 대조 단어
# 10종(schedule/water/tomato/advertisement/can't/vitamin/garage/leisure/privacy/herb)
# 에서 전부 정확했다 (docs/tasks/LAN-373/plan.md 진행 기록).
#
# 주의: espeak의 en-au는 en-gb와 음소가 동일하다(호주 억양은 음성 실현 차이로만 처리).
# 실제 호주 영어는 BATH 모음 단어(dance류)에서 영국과 갈리므로 해당 단어는 검수 플래그를
# 붙인다. 대조 정의가 실제 TTS 발음과 어긋나면 landit-iac의 verify-accent가 게시 전에
# 잡아낸다.
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

_ESPEAK_VOICE = {"EN_US": "en-us", "EN_GB": "en-gb", "EN_AU": "en-au"}
_ESPEAK_TIMEOUT_SECONDS = 10.0

# 이중모음을 단모음보다 먼저 매칭해야 한다 (긴 것 우선)
_IPA_VOWELS: tuple[tuple[str, str], ...] = (
    # espeak 영국 발음이 here/near/tired를 iə/aɪə로 적지만 실제로는 한 음절이다
    ("aɪə", "eyer"), ("aʊə", "ower"), ("iːə", "eer"), ("uːə", "oor"),
    ("iə", "eer"), ("uə", "oor"),
    ("eɪ", "ay"), ("aɪ", "eye"), ("ɔɪ", "oy"), ("aʊ", "ow"),
    ("əʊ", "oh"), ("oʊ", "oh"), ("ɪə", "eer"), ("eə", "air"), ("ʊə", "oor"),
    ("iː", "ee"), ("ɑː", "ah"), ("ɔː", "aw"), ("uː", "oo"), ("ɜː", "er"),
    ("ɪ", "ih"), ("ɛ", "eh"), ("e", "eh"), ("æ", "a"), ("a", "a"),
    ("ɒ", "o"), ("ɔ", "aw"), ("ʊ", "uu"), ("ʌ", "uh"), ("ə", "uh"), ("ɚ", "er"),
    ("ɐ", "uh"), ("ᵻ", "ih"), ("i", "ee"), ("u", "oo"),
)
_IPA_CONSONANTS: tuple[tuple[str, str], ...] = (
    ("tʃ", "ch"), ("dʒ", "j"), ("ʃ", "sh"), ("ʒ", "zh"),
    ("θ", "th"), ("ð", "th"), ("ŋ", "ng"), ("ɡ", "g"),
    ("ɹ", "r"), ("ɾ", "d"), ("j", "y"), ("ʔ", ""), ("ɬ", "l"),
)
_VOWEL_SYMBOLS = tuple(symbol for symbol, _ in _IPA_VOWELS)

# 미국식 æ가 영국식 ɑː/a로 갈리는 BATH 모음 단어는 실제 호주 발음이 영국과 다를 수
# 있으므로(호주는 æ 유지 경향) EN_AU 생성 시 검수 대상으로 표시한다.
BATH_VOWEL_REVIEW_NOTE = "BATH 모음 단어 — 실제 호주 발음은 영국(ah)과 다를 수 있음"


@dataclass(frozen=True)
class IpaPronunciation:
    ipa: str
    syllable_count: int
    stress_index: int
    # 음절별 respelling. 예: water(en-gb) → ["waw", "tuh"]
    syllable_respellings: list[str]


class EspeakUnavailableError(Exception):
    """espeak-ng 미설치 또는 실행 실패."""


def espeak_available() -> bool:
    return shutil.which("espeak-ng") is not None


@lru_cache(maxsize=4096)
def get_pronunciation(word: str, locale: str) -> IpaPronunciation | None:
    """단어 하나의 IPA 발음을 얻는다. 파싱 불가면 None."""
    ipa = _run_espeak(word, locale)
    if not ipa:
        return None
    return parse_ipa(ipa)


def _run_espeak(word: str, locale: str) -> str:
    if not espeak_available():
        raise EspeakUnavailableError("espeak-ng is not installed (brew install espeak-ng)")
    try:
        result = subprocess.run(
            ["espeak-ng", "-v", _ESPEAK_VOICE[locale], "-q", "--ipa", word],
            capture_output=True,
            text=True,
            timeout=_ESPEAK_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise EspeakUnavailableError("espeak-ng timed out") from error
    if result.returncode != 0:
        raise EspeakUnavailableError(f"espeak-ng failed: {result.stderr.strip()[:120]}")
    return result.stdout.strip().replace(" ", "")


def parse_ipa(ipa: str) -> IpaPronunciation | None:
    """IPA 문자열에서 음절 수·강세 위치·음절별 respelling을 뽑는다.

    espeak은 음절 경계를 주지 않으므로 모음 핵 기준으로 나눈다. 강세 기호 ˈ는
    강세 음절의 시작 앞에 붙으므로, ˈ 뒤에 처음 나오는 모음 핵이 강세 음절이다.
    """
    tokens = _tokenize(ipa)
    if tokens is None:
        return None

    nuclei_indexes = [
        index for index, (kind, _, _) in enumerate(tokens) if kind == "vowel"
    ]
    if not nuclei_indexes:
        return None

    stress_index = 0
    pending_stress = False
    for index, (kind, symbol, _) in enumerate(tokens):
        if kind == "stress" and symbol == "ˈ":
            pending_stress = True
        elif kind == "vowel" and pending_stress:
            stress_index = nuclei_indexes.index(index)
            break

    syllables = _split_syllables(tokens, nuclei_indexes)
    return IpaPronunciation(
        ipa=ipa,
        syllable_count=len(nuclei_indexes),
        stress_index=stress_index,
        syllable_respellings=["".join(part) for part in syllables],
    )


def respell(ipa: str) -> str | None:
    """IPA 전체를 · 구분 respelling으로 바꾼다. 예: wˈɔːtə → waw·tuh"""
    parsed = parse_ipa(ipa)
    if parsed is None:
        return None
    return display_respelling(parsed.syllable_respellings)


def display_respelling(syllable_respellings: list[str]) -> str:
    """음절 respelling을 화면용 문자열로 잇는다.

    판정 묘사(userDisplay)가 쓰는 스타일("nuh·ssing")과 맞도록 어미 ihng은
    ing으로 정규화한다 — 원어민/유저 표기를 나란히 비교하는 카드에서 표기 방식이
    다르면 그 자체가 거짓 차이로 보인다.
    """
    parts = [
        part[:-4] + "ing" if part.endswith("ihng") else part
        for part in syllable_respellings
    ]
    return "·".join(parts)


def _tokenize(ipa: str) -> list[tuple[str, str, str]] | None:
    """IPA를 (종류, 기호, respelling) 토큰 목록으로 나눈다. 미지의 기호가 있으면 None."""
    tokens: list[tuple[str, str, str]] = []
    position = 0
    while position < len(ipa):
        character = ipa[position]
        if character in "ˈˌ":
            tokens.append(("stress", character, ""))
            position += 1
            continue
        if character in "ː̩̆‿":
            position += 1
            continue
        # "iəʊ"(video의 i+əʊ)는 iə 이중모음이 아니라 i와 əʊ 두 핵이다
        if ipa.startswith("iəʊ", position) or ipa.startswith("uəʊ", position):
            tokens.append(("vowel", ipa[position], "ee" if ipa[position] == "i" else "oo"))
            position += 1
            continue
        matched = False
        for symbol, spelling in _IPA_VOWELS:
            if ipa.startswith(symbol, position):
                tokens.append(("vowel", symbol, spelling))
                position += len(symbol)
                matched = True
                break
        if matched:
            continue
        for symbol, spelling in _IPA_CONSONANTS:
            if ipa.startswith(symbol, position):
                tokens.append(("consonant", symbol, spelling))
                position += len(symbol)
                matched = True
                break
        if matched:
            continue
        if re.fullmatch(r"[a-z']", character):
            tokens.append(("consonant", character, character))
            position += 1
            continue
        return None
    return tokens


def _split_syllables(
    tokens: list[tuple[str, str, str]], nuclei_indexes: list[int]
) -> list[list[str]]:
    """모음 핵 하나당 음절 하나. 핵 사이 자음은 마지막 하나만 다음 음절 onset으로 넘긴다."""
    spellings = [spelling for _, _, spelling in tokens]
    kinds = [kind for kind, _, _ in tokens]

    boundaries = []
    for current, following in zip(nuclei_indexes, nuclei_indexes[1:]):
        consonants = [
            index
            for index in range(current + 1, following)
            if kinds[index] == "consonant"
        ]
        boundaries.append(consonants[-1] if consonants else following)

    pieces: list[list[str]] = []
    start = 0
    for boundary in boundaries:
        pieces.append(
            [spellings[i] for i in range(start, boundary) if kinds[i] != "stress"]
        )
        start = boundary
    pieces.append(
        [spellings[i] for i in range(start, len(tokens)) if kinds[i] != "stress"]
    )
    return pieces
