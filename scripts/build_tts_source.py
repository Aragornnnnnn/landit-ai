# LAN-373 기준 데이터(reference_*.json)를 LAN-377 TTS 파이프라인 소스로 변환한다.
#
# - 3개 locale의 accentContrast를 단어별로 병합한다 (verify-accent가 locale별로 조회)
# - 패턴형 표현("be busy ~ing", "+목적어" 등)은 expressionText를 생략해
#   표현 음성 생성을 건너뛴다 (문장·단어 음성은 정상 생성)
#
# 사용법:
#   .venv/bin/python scripts/build_tts_source.py \
#       --expressions expressions_full.json --reference-dir refdata/final \
#       --out tts_source_full.json [--ids 164,177]
import argparse
import json
import re
from pathlib import Path

LOCALES = ("EN_US", "EN_GB", "EN_AU")
# 표현 텍스트에 이 문자가 있으면 발화 불가능한 패턴형으로 본다
_TEMPLATED = re.compile(r"[~가-힣()+]")


def build(expressions_path: Path, reference_dir: Path, ids: set[int] | None) -> dict:
    full = json.loads(expressions_path.read_text(encoding="utf-8"))
    references = {
        locale: {
            entry["expressionId"]: entry
            for entry in json.loads(
                (reference_dir / f"reference_{locale}.json").read_text(
                    encoding="utf-8"
                )
            )
        }
        for locale in LOCALES
    }

    expressions = []
    for source in full:
        expression_id = source["expressionId"]
        if ids is not None and expression_id not in ids:
            continue
        words = []
        for base_word in references["EN_US"][expression_id]["words"]:
            item = {"order": base_word["order"], "word": base_word["word"]}
            contrasts = {}
            for locale in LOCALES:
                reference_word = next(
                    w
                    for w in references[locale][expression_id]["words"]
                    if w["order"] == base_word["order"]
                )
                contrast = reference_word.get("accentContrast")
                if contrast:
                    contrasts[locale] = {
                        "expected": contrast["expected"],
                        "other": contrast["other"],
                    }
            if contrasts:
                item["accentContrast"] = contrasts
            words.append(item)

        entry = {
            "expressionId": expression_id,
            "sentenceText": source["sentenceText"],
            "accentLocales": list(LOCALES),
            "words": words,
        }
        if not _TEMPLATED.search(source["expressionText"]):
            entry["expressionText"] = source["expressionText"]
        expressions.append(entry)

    return {
        "schemaVersion": 1,
        "environment": "production",
        "expressions": expressions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN-377 TTS 소스 변환")
    parser.add_argument("--expressions", required=True, type=Path)
    parser.add_argument("--reference-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ids", help="쉼표 구분 expressionId 부분집합 (파일럿용)")
    args = parser.parse_args()

    ids = (
        {int(value) for value in args.ids.split(",")} if args.ids else None
    )
    source = build(args.expressions, args.reference_dir, ids)
    args.out.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")

    total = len(source["expressions"])
    no_expression = sum(
        1 for entry in source["expressions"] if "expressionText" not in entry
    )
    contrast_words = sum(
        1
        for entry in source["expressions"]
        for word in entry["words"]
        if "accentContrast" in word
    )
    print(
        f"표현 {total}개 (표현 음성 생략 {no_expression}) · "
        f"대조 단어 {contrast_words}개 → {args.out}"
    )


if __name__ == "__main__":
    main()
