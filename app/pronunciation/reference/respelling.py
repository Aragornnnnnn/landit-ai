# 발음 사전에서 학습자용 음절·강세 기준 데이터를 만드는 모듈
#
# AI 호출 없이 사전만으로 생성한다. BE의 words_payload 형식에 맞춘 값을 낸다:
#   stressDisplay "hik·ing", syllables ["hik","ing"], stressIndex 0
#
# 두 사전을 조합한다:
#   - 음절 분리: pyphen(철자 기반). 음소를 글자로 옮기면 "like"가 "leyek"처럼 읽을 수
#     없는 표기가 되므로 철자를 쪼갠다. LAN-209에서 사람이 만든 기준
#     (poc_manifest_tts.json)도 "hik·ing", "yes·ter·day"처럼 철자 기반이다.
#   - 강세 위치: CMUdict(ARPABET). 모음 phoneme 뒤 숫자가 강세다 (1=1강세, 2=2강세).
#
# 두 사전의 음절 수가 어긋나면 강세를 음절에 매핑할 수 없으므로 검수 대상으로 표시한다.
# 문장 내 무강세 기능어는 stressIndex -1로 둔다 (위 선례와 동일).
from dataclasses import dataclass

_VOWELS = frozenset("AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW".split())

SYLLABLE_SEPARATOR = "·"


@dataclass(frozen=True)
class WordPronunciation:
    word: str
    phonemes: str
    syllables: list[str]
    stress_index: int
    native_display: str
    # 사전 간 음절 수 불일치 등으로 사람 검수가 필요한 사유. 없으면 None.
    review_reason: str | None = None


def build_pronunciation(
    word: str,
    phonemes: list[str],
    syllables: list[str],
    function_word: bool = False,
) -> WordPronunciation:
    phoneme_syllable_count = sum(1 for phoneme in phonemes if _is_vowel(phoneme))
    review_reason = None

    if function_word:
        stress_index = -1
    elif not phonemes:
        stress_index = 0
        review_reason = "발음 사전에 없는 단어"
    elif phoneme_syllable_count != len(syllables):
        stress_index = 0
        review_reason = (
            f"음절 수 불일치: 철자 {len(syllables)} vs 발음 {phoneme_syllable_count}"
        )
    else:
        stress_index = _stress_index(phonemes)

    return WordPronunciation(
        word=word,
        phonemes=" ".join(phonemes),
        syllables=syllables,
        stress_index=stress_index,
        native_display=SYLLABLE_SEPARATOR.join(syllables),
        review_reason=review_reason,
    )


def _is_vowel(phoneme: str) -> bool:
    return phoneme.rstrip("0123456789") in _VOWELS


def _stress_index(phonemes: list[str]) -> int:
    """1강세 모음이 몇 번째 음절인지. 없으면 2강세, 그것도 없으면 첫 음절."""
    secondary = -1
    syllable = 0
    for phoneme in phonemes:
        if not _is_vowel(phoneme):
            continue
        marker = phoneme[-1]
        if marker == "1":
            return syllable
        if marker == "2" and secondary < 0:
            secondary = syllable
        syllable += 1
    return secondary if secondary >= 0 else 0
