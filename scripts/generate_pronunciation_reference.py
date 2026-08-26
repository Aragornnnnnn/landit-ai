# LAN-373 발음 기준 데이터 생성 — 문장의 단어별 음절·강세·respelling·억양 대조를 만든다.
#
# AI 호출 없이 사전만 쓴다. locale별 발음 소스:
#   EN_US: CMUdict (ARPABET)
#   EN_GB: espeak-ng en-gb (IPA) — 억양 대조 단어 10종 검증 완료
#   EN_AU: espeak-ng en-au — 음소가 en-gb와 동일해 사실상 GB 재사용.
#          BATH 모음 단어(dance류)는 실제 호주 발음이 다를 수 있어 검수 표시한다.
#
# stressDisplay(강세 표시용)는 철자를 발음 음절 수로 쪼갠 것이고(hik·ing), 발음 respelling
# (heye·kihng)은 억양 대조 보기 초안에만 쓴다.
#
# accentContrast: 같은 단어의 미국식/대상 억양 발음이 다르면 양자택일 보기 초안을
# 생성한다. 최종 문안은 사람 검수로 확정한다 (초안은 respelling 표기).
#
# 사용법:
#   .venv/bin/python scripts/generate_pronunciation_reference.py \
#       --sentence "Could you give me a cup of water please?" --locale EN_GB
#   .venv/bin/python scripts/generate_pronunciation_reference.py \
#       --input expressions.json --locale EN_AU --out-dir out/reference
import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pronunciation.reference import espeak  # noqa: E402
from app.pronunciation.reference.respelling import (  # noqa: E402
    build_pronunciation,
)
from app.pronunciation.reference.syllables import split_syllables  # noqa: E402

# 문장 안에서 보통 강세를 받지 않는 기능어. stressIndex -1로 둔다.
FUNCTION_WORDS = frozenset(
    """a an and are as at be been but by for from had has have he her his in is it
    its me my of on or our she that the their them there they to was we were will
    with you your""".split()
)

LOCALES = ("EN_US", "EN_GB", "EN_AU")

# ── 검수 확정 데이터 (2026-08-26, 981개 전량 검수) ─────────────────────────────
# 자동 분리가 실패한 단어의 수동 음절 분리. 철자를 보존하는 분할만 쓴다.
SYLLABLE_OVERRIDES: dict[str, list[str]] = {
    "ac": ["A", "C"],
    "actually": ["ac", "tu", "al", "ly"],
    "advertisement": ["ad", "ver", "tise", "ment"],
    "area": ["a", "re", "a"],
    "basically": ["ba", "sic", "ally"],
    "cafeteria": ["ca", "fe", "te", "ri", "a"],
    "chaotic": ["cha", "o", "tic"],
    "chloe": ["Chlo", "e"],
    "chocolate": ["choc", "olate"],
    "chronically": ["chron", "ical", "ly"],
    "completely": ["com", "plete", "ly"],
    "definitely": ["def", "i", "nite", "ly"],
    "lifesaver": ["life", "sa", "ver"],
    "shameless": ["shame", "less"],
    "curiosity": ["cu", "ri", "os", "i", "ty"],
    "difference": ["dif", "ference"],
    "different": ["dif", "ferent"],
    "doable": ["do", "a", "ble"],
    "earlier": ["ear", "li", "er"],
    "easier": ["eas", "i", "er"],
    "every": ["ev", "ery"],
    "everyone's": ["ev", "ery", "one's"],
    "everything": ["ev", "ery", "thing"],
    "experiences": ["ex", "pe", "ri", "en", "ces"],
    "gatekeeping": ["gate", "keep", "ing"],
    "goosebumps": ["goose", "bumps"],
    "graduation": ["grad", "u", "a", "tion"],
    "happier": ["hap", "pi", "er"],
    "homework": ["home", "work"],
    "hour": ["hour"],
    "hours": ["hours"],
    "iceland": ["Ice", "land"],
    "idea": ["i", "de", "a"],
    "interesting": ["in", "teres", "ting"],
    "it'd": ["it", "'d"],
    "it'll": ["it", "'ll"],
    "korean": ["Ko", "re", "an"],
    "kyoto": ["Ky", "o", "to"],
    "layover": ["lay", "o", "ver"],
    "mmm": ["mmm"],
    "obviously": ["ob", "vi", "ous", "ly"],
    "our": ["our"],
    "pdf": ["P", "D", "F"],
    "period": ["pe", "ri", "od"],
    "player": ["play", "er"],
    "quiet": ["qui", "et"],
    "reality": ["re", "al", "i", "ty"],
    "relatively": ["rel", "a", "tive", "ly"],
    "requirements": ["re", "quire", "ments"],
    "scenario": ["sce", "na", "ri", "o"],
    "serious": ["se", "ri", "ous"],
    "seriously": ["se", "ri", "ous", "ly"],
    "shh": ["shh"],
    "situationship": ["sit", "u", "a", "tion", "ship"],
    "takoyaki": ["ta", "ko", "ya", "ki"],
    "technically": ["tech", "nical", "ly"],
    "unique": ["u", "nique"],
    "unusually": ["un", "u", "su", "al", "ly"],
    "usually": ["u", "su", "al", "ly"],
    "video": ["vi", "de", "o"],
    "videos": ["vi", "de", "os"],
    "whatsoever": ["what", "so", "ev", "er"],
}

# 억양 대조에서 제외한 단어. 이유:
#   happy-tensing — 어말 -y를 영국이 ih로 낸다는 espeak 표기는 낡은 RP라 현대 영국
#     발음(ee)과 다르다. 학습자에게 틀린 기준을 들이대게 되므로 제외.
#   rhotic-only — r 유무만 다른 경우는 계통 차이라 minor로 걸러야 하나 부수 모음
#     표기가 달라 major로 새어 들어온 것들.
#   espeak-quirk — espeak 표기 오류거나 실제 표준 발음과 다른 것.
DROPPED_CONTRAST_WORDS: dict[str, str] = {
    "alley": "happy-tensing", "early": "happy-tensing", "every": "happy-tensing",
    "perfectly": "happy-tensing", "really": "happy-tensing",
    "before": "rhotic-only", "december": "rhotic-only", "layover": "rhotic-only",
    "recharge": "rhotic-only", "record": "rhotic-only", "report": "rhotic-only",
    "sources": "rhotic-only", "repair": "rhotic-only",
    "possible": "약화 모음 표기 차이", "possibly": "약화 모음 표기 차이",
    "bottom": "약화 모음 표기 차이", "boxes": "약화 모음 표기 차이",
    "chaotic": "약화 모음 표기 차이", "obsessed": "약화 모음 표기 차이",
    "moral": "약화 모음 표기 차이", "scenario": "약화 모음 표기 차이",
    "library": "약화 모음 표기 차이", "curry": "hurry-furry 병합(불안정)",
    "mall": "espeak-quirk", "launch": "espeak-quirk", "you're": "espeak-quirk",
    "beaten": "espeak-quirk(성문음 표기 깨짐)", "kyoto": "espeak-quirk(고유명사)",
    "video": "espeak-quirk", "videos": "espeak-quirk",
    "requirements": "espeak-quirk(이중모음 표기)",
}

# EN_AU는 BATH 모음 대조를 판정에 쓰지 않는다. 실제 호주 발음이 미국식 모음(æ)을
# 유지하는 경우가 많아, 영국 기준을 들이대면 정당한 호주 발음이 오탐이 된다.
AU_DROPS_BATH_CONTRASTS = True
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReferenceWord:
    word: str
    phonemes: str
    syllables: list[str]
    stress_index: int
    native_display: str
    native_respelling: str  # 발음 오류 카드에서 userDisplay와 비교하는 원어민 발음 표기
    review_reason: str | None
    contrast_expected: str | None  # 대상 억양 발음 respelling (보기 초안)
    contrast_other: str | None  # 미국식 발음 respelling (보기 초안)
    contrast_error_type: str | None  # PHONEME | STRESS
    contrast_tier: str | None  # major(판정 사용) | minor(참고용)


# 미↔영의 계통적 실현 차이(r 발음, LOT/GOAT 모음 등)를 동일시하는 정규화.
# 정규화 후에도 다르면 어휘·flap·BATH·강세 같은 '가르칠 만한' 차이(major)로 본다.
# 100문장 실측에서 대조 80개 중 대부분이 sorry/what/here류 계통 차이 스팸이었고,
# 이런 미세 차이는 양자택일 판별이 검증된 유형(water/can't/tomato/schedule/
# advertisement)에 들지 않는다.
_MINOR_IPA_NORMALIZATION: tuple[tuple[str, str], ...] = (
    ("ˈ", ""), ("ˌ", ""), ("ː", ""),
    ("ɚ", "ə"),  # 미국식 r색 슈와
    ("aɪə", "aɪ"), ("aʊə", "aʊ"), ("iə", "ɪ"), ("eə", "ɛ"), ("ʊə", "ʊ"),
    ("ɪə", "ɪ"),  # 중심 이중모음 = 모음+r의 비rhotic 실현
    ("əʊ", "oʊ"),  # GOAT 모음 표기 차이
    ("ɒ", "ɑ"), ("ʌ", "ɑ"),  # LOT/STRUT 실현 차이 (what/not/got/sorry류)
    ("æ", "a"), ("ɐ", "ə"),  # espeak이 미/영에서 같은 모음을 다르게 적는 표기 차이
    ("ɹ", ""),  # rhotic r 유무
)


# BATH 모음 단어: 미국식 æ ↔ 영국식 ɑ(ː)로 갈리는 대표 어휘. espeak이 이들을
# ɑː(can't)와 a(after, dance)로 비일관되게 적어 기호만으로는 TRAP(계통 차이)과
# 구분할 수 없으므로 목록으로 명시해 major로 유지한다.
_BATH_WORDS = frozenset(
    """after afternoon answer ask aunt bath branch brass can't cast castle chance
    class command dance demand draft example fast glass grant grass half laugh
    last pass past path plant rather sample shan't staff task vast""".split()
)


def _stress_marked(syllables: list[str], stress_index: int) -> str:
    marked = [
        part.upper() if index == stress_index else part
        for index, part in enumerate(syllables)
    ]
    ordinal = {0: "1st", 1: "2nd", 2: "3rd"}.get(stress_index, f"{stress_index + 1}th")
    return f"stress on the {ordinal} syllable ({'·'.join(marked)})"


def _normalize_for_tier(ipa: str) -> str:
    normalized = ipa
    for source, target in _MINOR_IPA_NORMALIZATION:
        normalized = normalized.replace(source, target)
    return normalized


def tokenize(sentence: str) -> list[str]:
    # 숫자 단어("9")도 포함한다 — API가 정렬 시 철자("nine")로 변환해 처리한다
    return re.findall(r"[A-Za-z0-9']+", sentence)


_CMUDICT_CACHE: dict | None = None


def _cmudict_entries() -> dict:
    global _CMUDICT_CACHE
    if _CMUDICT_CACHE is None:
        import cmudict

        _CMUDICT_CACHE = cmudict.dict()
    return _CMUDICT_CACHE


def _resolve_syllables(word: str, syllable_count: int) -> tuple[list[str], str | None]:
    """검수 확정 분리표 → n't 규칙 → 자동 분리 순으로 음절을 정한다."""
    override = SYLLABLE_OVERRIDES.get(word.lower())
    if override is not None:
        return override, None
    from app.pronunciation.reference.syllables import split_with_nt_suffix

    split = split_with_nt_suffix(word, syllable_count) or split_syllables(
        word, syllable_count
    )
    if split is None:
        return [word], "철자 음절 분리 실패 — 수동 분리 필요"
    return split, None


def _cmudict_word(word: str, function_word: bool):
    entries = _cmudict_entries()
    pronunciations = entries.get(word.lower().strip("'"), [])
    phonemes = pronunciations[0] if pronunciations else []
    if not phonemes:
        # cmudict에 없는 신조어·고유명사(adulting, hoodie 등)는 espeak 미국
        # 발음으로 대체한다 (981개 검수에서 42개 확인)
        ipa, review, syllables, stress_index = _espeak_word(
            word, "EN_US", function_word
        )
        if ipa:
            built = build_pronunciation(
                word=word, phonemes=[], syllables=syllables,
                function_word=function_word,
            )
            built = type(built)(
                word=word, phonemes=ipa, syllables=syllables,
                stress_index=stress_index,
                native_display="·".join(syllables),
                review_reason=review,
            )
            return built, review
        return build_pronunciation(
            word=word, phonemes=[], syllables=[word],
            function_word=function_word,
        ), "발음 사전에 없는 단어"

    syllable_count = sum(
        1 for phoneme in phonemes if phoneme.rstrip("0123456789")
        in {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY",
            "OW", "OY", "UH", "UW"}
    )
    split, review = _resolve_syllables(word, syllable_count)
    built = build_pronunciation(
        word=word, phonemes=phonemes, syllables=split, function_word=function_word
    )
    # 검수 분리표가 발음 음절 수와 다른 표기를 확정한 경우(chocolate 등)는
    # 불일치 검수 플래그를 무시한다
    if word.lower() in SYLLABLE_OVERRIDES:
        return type(built)(
            word=built.word, phonemes=built.phonemes, syllables=built.syllables,
            stress_index=built.stress_index, native_display=built.native_display,
            review_reason=None,
        ), review
    return built, review or built.review_reason


def _espeak_word(word: str, locale: str, function_word: bool):
    """(IPA 문자열, 검수 사유, 철자 음절, 강세 인덱스)를 반환한다."""
    pronunciation = espeak.get_pronunciation(word, locale)
    if pronunciation is None:
        return "", "espeak 발음 파싱 실패 — 수동 입력 필요", [word], 0
    split, review = _resolve_syllables(word, pronunciation.syllable_count)
    return (
        pronunciation.ipa,
        review,
        split,
        -1 if function_word else pronunciation.stress_index,
    )


def _contrast_for(
    word: str, locale: str
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """대상 억양과 반대 진영(미↔영)의 발음이 다르면 양자택일 보기 초안을 만든다.

    반환: (기대 respelling, 반대 respelling, 오류 유형, 등급, 검수 사유)
    """
    other_locale = "EN_GB" if locale == "EN_US" else "EN_US"
    us = espeak.get_pronunciation(word, other_locale)
    target = espeak.get_pronunciation(word, locale)
    if us is None or target is None:
        return None, None, None, None, None
    us_spelling = "·".join(us.syllable_respellings)
    target_spelling = "·".join(target.syllable_respellings)
    if us_spelling == target_spelling and us.stress_index == target.stress_index:
        return None, None, None, None, None

    stress_differs = (
        us.syllable_count == target.syllable_count
        and us.stress_index != target.stress_index
    )
    is_stress_only = stress_differs and us_spelling == target_spelling
    if is_stress_only:
        # 강세 대조는 철자가 같아 보기 두 개가 동일해지므로 강세 음절을 표기한다
        # (스파이크에서 검증한 "stress on the Nth syllable (...)" 형식)
        target_spelling = _stress_marked(target.syllable_respellings, target.stress_index)
        us_spelling = _stress_marked(us.syllable_respellings, us.stress_index)
    is_bath_word = word.lower() in _BATH_WORDS
    tier = (
        "major"
        if stress_differs
        or is_bath_word
        or _normalize_for_tier(us.ipa) != _normalize_for_tier(target.ipa)
        else "minor"
    )
    # 검수 확정: 제외 목록과 AU의 BATH 정책을 적용한다
    dropped_reason = DROPPED_CONTRAST_WORDS.get(word.lower())
    if dropped_reason:
        tier = f"dropped({dropped_reason})"
    elif locale == "EN_AU" and is_bath_word and AU_DROPS_BATH_CONTRASTS:
        tier = "dropped(호주 BATH 정책 — 미국식 모음도 정당한 호주 발음)"
    error_type = "STRESS" if is_stress_only else "PHONEME"
    review = None
    # AU BATH 정책이 꺼져 있을 때만 검수 표시를 남긴다 (켜져 있으면 이미 제외됨)
    if locale == "EN_AU" and is_bath_word and not AU_DROPS_BATH_CONTRASTS:
        review = espeak.BATH_VOWEL_REVIEW_NOTE
    return target_spelling, us_spelling, error_type, tier, review


def build_words(sentence: str, locale: str) -> list[ReferenceWord]:
    from app.pronunciation.numbers import spell_out

    results = []
    for word in tokenize(sentence):
        spelled = spell_out(word)
        if spelled is not None:
            # 숫자 단어는 판정에서 제외되므로 발화 철자만 기록해 둔다
            results.append(
                ReferenceWord(
                    word=word,
                    phonemes="",
                    syllables=[word],
                    stress_index=0,
                    native_display=word,
                    native_respelling=spelled,
                    review_reason=f"숫자 단어 — 판정 제외, 정렬은 '{spelled}'",
                    contrast_expected=None,
                    contrast_other=None,
                    contrast_error_type=None,
                    contrast_tier=None,
                )
            )
            continue
        function_word = word.lower() in FUNCTION_WORDS
        reviews: list[str] = []

        if locale == "EN_US":
            built, review = _cmudict_word(word, function_word)
            phonemes = built.phonemes
            syllables = built.syllables
            stress_index = built.stress_index
            if review:
                reviews.append(review)
        else:
            phonemes, review, syllables, stress_index = _espeak_word(
                word, locale, function_word
            )
            if review:
                reviews.append(review)

        contrast_expected = contrast_other = contrast_type = contrast_tier = None
        if not function_word:
            (
                contrast_expected,
                contrast_other,
                contrast_type,
                contrast_tier,
                contrast_review,
            ) = _contrast_for(word, locale)
            if contrast_review:
                reviews.append(contrast_review)

        pronunciation = espeak.get_pronunciation(word, locale)
        native_respelling = (
            espeak.display_respelling(pronunciation.syllable_respellings)
            if pronunciation is not None
            else word
        )
        results.append(
            ReferenceWord(
                word=word,
                phonemes=phonemes,
                syllables=syllables,
                stress_index=stress_index,
                native_display="·".join(syllables),
                native_respelling=native_respelling,
                review_reason="; ".join(reviews) or None,
                contrast_expected=contrast_expected,
                contrast_other=contrast_other,
                contrast_error_type=contrast_type,
                contrast_tier=contrast_tier,
            )
        )
    return results


def to_payload(words: list[ReferenceWord]) -> list[dict]:
    payload = []
    for index, word in enumerate(words):
        item = {
            "order": index + 1,
            "word": word.word,
            "phonemes": word.phonemes,
            "syllables": word.syllables,
            "stressIndex": word.stress_index,
            "stressDisplay": word.native_display,
            "pronunciationDisplay": word.native_respelling,
        }
        # minor(계통적 실현 차이)는 판정에 쓰지 않고 검수 CSV에만 남긴다
        if word.contrast_expected and word.contrast_tier == "major":
            is_stress = word.contrast_expected.startswith("stress on")
            item["accentContrast"] = {
                "expected": word.contrast_expected
                if is_stress
                else f"sounds like 「{word.contrast_expected}」",
                "other": word.contrast_other
                if is_stress
                else f"sounds like 「{word.contrast_other}」",
                "errorType": word.contrast_error_type,
            }
        payload.append(item)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN-373 발음 기준 데이터 생성")
    parser.add_argument("--sentence", help="단일 문장으로 생성한다")
    parser.add_argument(
        "--input",
        type=Path,
        help='표현 JSON: [{"expressionId": 1, "sentenceText": "..."}]',
    )
    parser.add_argument("--locale", default="EN_US", choices=LOCALES)
    parser.add_argument("--out-dir", type=Path, default=Path("out/reference"))
    args = parser.parse_args()

    if not args.sentence and not args.input:
        parser.error("--sentence 또는 --input 중 하나가 필요하다")
    if args.locale != "EN_US" and not espeak.espeak_available():
        parser.error("EN_GB/EN_AU 생성에는 espeak-ng가 필요하다 (brew install espeak-ng)")

    if args.sentence:
        sources = [{"expressionId": None, "sentenceText": args.sentence}]
    else:
        sources = json.loads(args.input.read_text(encoding="utf-8"))

    results = []
    review_rows = []
    for source in sources:
        words = build_words(source["sentenceText"], args.locale)
        results.append(
            {
                "expressionId": source.get("expressionId"),
                "accentLocale": args.locale,
                "sentenceText": source["sentenceText"],
                "words": to_payload(words),
            }
        )
        for index, word in enumerate(words):
            review_rows.append(
                {
                    "expressionId": source.get("expressionId"),
                    "order": index + 1,
                    "word": word.word,
                    "stressDisplay": word.native_display,
                    "pronunciationDisplay": word.native_respelling,
                    "stressIndex": word.stress_index,
                    "phonemes": word.phonemes,
                    "contrastExpected": word.contrast_expected or "",
                    "contrastOther": word.contrast_other or "",
                    "contrastType": word.contrast_error_type or "",
                    "contrastTier": word.contrast_tier or "",
                    "reviewReason": word.review_reason or "",
                }
            )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    payload_path = args.out_dir / f"reference_{args.locale}.json"
    payload_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    csv_path = args.out_dir / f"reference_{args.locale}_review.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(review_rows[0]))
        writer.writeheader()
        writer.writerows(review_rows)

    contrast_count = sum(1 for row in review_rows if row["contrastTier"] == "major")
    needs_review = [row for row in review_rows if row["reviewReason"]]
    for row in review_rows:
        marker = "검수" if row["reviewReason"] else ("대조" if row["contrastExpected"] else "  ")
        contrast = (
            f" [{row['contrastType']}] {row['contrastExpected']} vs {row['contrastOther']}"
            if row["contrastExpected"]
            else ""
        )
        print(
            f"{marker} {row['order']:2d} {row['word']:16s} "
            f"{row['stressDisplay']:22s} 강세={row['stressIndex']:2d}"
            f"{contrast}  {row['reviewReason']}"
        )
    print(
        f"\n단어 {len(review_rows)}개 · 억양 대조 {contrast_count}개 · "
        f"검수 필요 {len(needs_review)}개\n"
        f"저장: {payload_path}\n      {csv_path}"
    )


if __name__ == "__main__":
    main()
