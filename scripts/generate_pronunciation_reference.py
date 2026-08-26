# LAN-373 발음 기준 데이터 생성 — 문장의 단어별 음절·강세·respelling·억양 대조를 만든다.
#
# AI 호출 없이 사전만 쓴다. locale별 발음 소스:
#   EN_US: CMUdict (ARPABET)
#   EN_GB: espeak-ng en-gb (IPA) — 억양 대조 단어 10종 검증 완료
#   EN_AU: espeak-ng en-au — 음소가 en-gb와 동일해 사실상 GB 재사용.
#          BATH 모음 단어(dance류)는 실제 호주 발음이 다를 수 있어 검수 표시한다.
#
# 화면용 nativeDisplay는 철자를 발음 음절 수로 쪼갠 것이고(hik·ing), 발음 respelling
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


@dataclass(frozen=True)
class ReferenceWord:
    word: str
    phonemes: str
    syllables: list[str]
    stress_index: int
    native_display: str
    review_reason: str | None
    contrast_expected: str | None  # 대상 억양 발음 respelling (보기 초안)
    contrast_other: str | None  # 미국식 발음 respelling (보기 초안)
    contrast_error_type: str | None  # PHONEME | STRESS


def tokenize(sentence: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", sentence)


def _cmudict_word(word: str, function_word: bool):
    import cmudict

    entries = cmudict.dict()
    pronunciations = entries.get(word.lower().strip("'"), [])
    phonemes = pronunciations[0] if pronunciations else []
    syllable_count = sum(
        1 for phoneme in phonemes if phoneme.rstrip("0123456789")
        in {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY",
            "OW", "OY", "UH", "UW"}
    )
    split = split_syllables(word, syllable_count) if syllable_count else None
    if split is None:
        split = [word]
        review = (
            "발음 사전에 없는 단어" if not phonemes else "철자 음절 분리 실패 — 수동 분리 필요"
        )
    else:
        review = None
    built = build_pronunciation(
        word=word, phonemes=phonemes, syllables=split, function_word=function_word
    )
    return built, review or built.review_reason


def _espeak_word(word: str, locale: str, function_word: bool):
    """(IPA 문자열, 검수 사유, 철자 음절, 강세 인덱스)를 반환한다."""
    pronunciation = espeak.get_pronunciation(word, locale)
    if pronunciation is None:
        return "", "espeak 발음 파싱 실패 — 수동 입력 필요", [word], 0
    split = split_syllables(word, pronunciation.syllable_count)
    review = None
    if split is None:
        split = [word]
        review = "철자 음절 분리 실패 — 수동 분리 필요"
    return (
        pronunciation.ipa,
        review,
        split,
        -1 if function_word else pronunciation.stress_index,
    )


def _contrast_for(word: str, locale: str) -> tuple[str | None, str | None, str | None, str | None]:
    """대상 억양과 반대 진영(미↔영)의 발음이 다르면 양자택일 보기 초안을 만든다."""
    other_locale = "EN_GB" if locale == "EN_US" else "EN_US"
    us = espeak.get_pronunciation(word, other_locale)
    target = espeak.get_pronunciation(word, locale)
    if us is None or target is None:
        return None, None, None, None
    us_spelling = "·".join(us.syllable_respellings)
    target_spelling = "·".join(target.syllable_respellings)
    if us_spelling == target_spelling and us.stress_index == target.stress_index:
        return None, None, None, None

    error_type = (
        "STRESS"
        if us.syllable_count == target.syllable_count
        and us.stress_index != target.stress_index
        and us_spelling == target_spelling
        else "PHONEME"
    )
    review = None
    # BATH 모음: 미국식 æ가 영국식 ɑː로 갈리는 단어. espeak en-au는 영국을 따르지만
    # 실제 호주 발음은 æ를 유지하는 경우가 많아 검수 대상으로 표시한다.
    if locale == "EN_AU" and "ɑː" in target.ipa and "æ" in us.ipa:
        review = espeak.BATH_VOWEL_REVIEW_NOTE
    return target_spelling, us_spelling, error_type, review


def build_words(sentence: str, locale: str) -> list[ReferenceWord]:
    results = []
    for word in tokenize(sentence):
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

        contrast_expected = contrast_other = contrast_type = None
        if not function_word:
            contrast_expected, contrast_other, contrast_type, contrast_review = (
                _contrast_for(word, locale)
            )
            if contrast_review:
                reviews.append(contrast_review)

        results.append(
            ReferenceWord(
                word=word,
                phonemes=phonemes,
                syllables=syllables,
                stress_index=stress_index,
                native_display="·".join(syllables),
                review_reason="; ".join(reviews) or None,
                contrast_expected=contrast_expected,
                contrast_other=contrast_other,
                contrast_error_type=contrast_type,
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
            "nativeDisplay": word.native_display,
        }
        if word.contrast_expected:
            item["accentContrast"] = {
                "expected": f"sounds like 「{word.contrast_expected}」",
                "other": f"sounds like 「{word.contrast_other}」",
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
                    "nativeDisplay": word.native_display,
                    "stressIndex": word.stress_index,
                    "phonemes": word.phonemes,
                    "contrastExpected": word.contrast_expected or "",
                    "contrastOther": word.contrast_other or "",
                    "contrastType": word.contrast_error_type or "",
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

    contrast_count = sum(1 for row in review_rows if row["contrastExpected"])
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
            f"{row['nativeDisplay']:22s} 강세={row['stressIndex']:2d}"
            f"{contrast}  {row['reviewReason']}"
        )
    print(
        f"\n단어 {len(review_rows)}개 · 억양 대조 {contrast_count}개 · "
        f"검수 필요 {len(needs_review)}개\n"
        f"저장: {payload_path}\n      {csv_path}"
    )


if __name__ == "__main__":
    main()
