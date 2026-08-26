# LAN-373 발음 기준 데이터 생성 — 문장의 단어별 음절·강세·respelling을 만든다.
#
# AI 호출 없이 사전만 쓴다 (pyphen + CMUdict). 출력은 BE의 words_payload 형식 JSON과
# 사람 검수용 CSV다.
#
# 사용법:
#   .venv/bin/python scripts/generate_pronunciation_reference.py \
#       --sentence "There's nothing like hiking to clear my head." \
#       --locale EN_US
#   .venv/bin/python scripts/generate_pronunciation_reference.py \
#       --input expressions.json --locale EN_US --out-dir out/reference
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pronunciation.reference.respelling import (  # noqa: E402
    WordPronunciation,
    build_pronunciation,
)

# 문장 안에서 보통 강세를 받지 않는 기능어. stressIndex -1로 둔다.
FUNCTION_WORDS = frozenset(
    """a an and are as at be been but by for from had has have he her his in is it
    its me my of on or our she that the their them there they to was we were will
    with you your""".split()
)

# CMUdict는 American English 사전이다. EN_GB/EN_AU는 별도 소스가 필요하다.
CMUDICT_LOCALES = frozenset({"EN_US"})
PYPHEN_LANG = {"EN_US": "en_US", "EN_GB": "en_GB", "EN_AU": "en_GB"}


def tokenize(sentence: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", sentence)


def build_words(sentence: str, locale: str) -> list[WordPronunciation]:
    import cmudict
    import pyphen

    entries = cmudict.dict()
    hyphenator = pyphen.Pyphen(lang=PYPHEN_LANG[locale])

    results = []
    for word in tokenize(sentence):
        lowered = word.lower()
        pronunciations = entries.get(lowered.strip("'"), [])
        phonemes = pronunciations[0] if pronunciations else []
        split = hyphenator.inserted(lowered, hyphen="\x00").split("\x00")
        results.append(
            build_pronunciation(
                word=word,
                phonemes=phonemes,
                syllables=split,
                function_word=lowered in FUNCTION_WORDS,
            )
        )
    return results


def to_payload(words: list[WordPronunciation]) -> list[dict]:
    return [
        {
            "order": index + 1,
            "word": word.word,
            "phonemes": word.phonemes,
            "syllables": word.syllables,
            "stressIndex": word.stress_index,
            "nativeDisplay": word.native_display,
        }
        for index, word in enumerate(words)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN-373 발음 기준 데이터 생성")
    parser.add_argument("--sentence", help="단일 문장으로 생성한다")
    parser.add_argument(
        "--input",
        type=Path,
        help='표현 JSON: [{"expressionId": 1, "sentenceText": "..."}]',
    )
    parser.add_argument("--locale", default="EN_US", choices=sorted(PYPHEN_LANG))
    parser.add_argument("--out-dir", type=Path, default=Path("out/reference"))
    args = parser.parse_args()

    if not args.sentence and not args.input:
        parser.error("--sentence 또는 --input 중 하나가 필요하다")

    if args.locale not in CMUDICT_LOCALES:
        print(
            f"경고: {args.locale}의 발음 사전이 없어 강세·음소를 미국식(CMUdict)으로 "
            f"생성한다. 어휘 차이가 있는 단어(schedule, tomato 등)는 검수가 필요하다.",
            file=sys.stderr,
        )

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

    needs_review = [row for row in review_rows if row["reviewReason"]]
    for row in review_rows:
        marker = "검수" if row["reviewReason"] else "  "
        print(
            f"{marker} {row['order']:2d} {row['word']:16s} "
            f"{row['nativeDisplay']:22s} 강세={row['stressIndex']:2d} "
            f"{row['reviewReason']}"
        )
    print(
        f"\n단어 {len(review_rows)}개 · 검수 필요 {len(needs_review)}개\n"
        f"저장: {payload_path}\n      {csv_path}"
    )


if __name__ == "__main__":
    main()
