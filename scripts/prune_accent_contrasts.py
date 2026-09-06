# LAN-373 verify-accent 실패 인스턴스의 억양 대조를 기준 데이터에서 제거한다.
#
# TTS(aura-2)의 GB·AU 음성은 연결 발화에서 미국식 flap을 쓰는 등 교과서적 억양
# 구분을 항상 재현하지 못한다 (전량 실측 338건). 참조 오디오가 들려주지 않는 억양을
# 학습자에게 요구할 수 없으므로, 검증에 실패한 (표현, locale, 단어) 인스턴스에서만
# accentContrast를 제거한다 — 통과한 인스턴스는 유지해 판정 기준과 참조 오디오를
# 일치시킨다.
#
# 사용법:
#   .venv/bin/python scripts/prune_accent_contrasts.py \
#       --problems accent_problems.txt --reference-dir refdata/final
# problems 형식 (verify-accent 출력 그대로):
#   930/EN_GB/word-4: 'Can't' sounded like ...
#   939/EN_AU/sentence: 'better' sounded like ...
import argparse
import json
import re
from pathlib import Path

_PROBLEM = re.compile(r"^(\d+)/(EN_\w+)/(\S+): '(.*?)' (?:sounded|could)")


def _parse_problems(problems_path: Path):
    # word-N 문제는 (expressionId, locale, order, 단어소문자)로 위치를 특정하고,
    # sentence 문제는 (expressionId, locale, 단어소문자)로 남는다.
    word_targets: set[tuple[int, str, int, str]] = set()
    sentence_targets: set[tuple[int, str, str]] = set()
    for line in problems_path.read_text(encoding="utf-8").splitlines():
        match = _PROBLEM.match(line.strip())
        if not match:
            continue
        expression_id, locale, kind, word = (
            int(match.group(1)),
            match.group(2),
            match.group(3),
            match.group(4).lower(),
        )
        order_match = re.fullmatch(r"word-(\d+)", kind)
        if order_match:
            word_targets.add((expression_id, locale, int(order_match.group(1)), word))
        else:
            sentence_targets.add((expression_id, locale, word))
    return word_targets, sentence_targets


def prune(problems_path: Path, reference_dir: Path) -> None:
    word_targets, sentence_targets = _parse_problems(problems_path)

    removed_total = 0
    for reference_path in sorted(reference_dir.glob("reference_EN_*.json")):
        if "review" in reference_path.name:
            continue
        entries = json.loads(reference_path.read_text(encoding="utf-8"))
        removed = 0
        for entry in entries:
            locale = entry["accentLocale"]
            expression_id = entry["expressionId"]
            by_lower: dict[str, list[dict]] = {}
            for word in entry["words"]:
                by_lower.setdefault(word["word"].lower(), []).append(word)

            for word in entry["words"]:
                for target_id, target_locale, order, target_word in word_targets:
                    if (target_id, target_locale, order) != (
                        expression_id,
                        locale,
                        word["order"],
                    ):
                        continue
                    if word["word"].lower() != target_word:
                        raise ValueError(
                            f"{expression_id}/{locale}/word-{order}: 기준 데이터의 "
                            f"단어({word['word']})와 문제 목록의 단어({target_word})가 "
                            f"다르다 — 입력을 확인하라"
                        )
                    if "accentContrast" in word:
                        del word["accentContrast"]
                        removed += 1

            for target_id, target_locale, target_word in sentence_targets:
                if (target_id, target_locale) != (expression_id, locale):
                    continue
                occurrences = by_lower.get(target_word, [])
                if len(occurrences) > 1:
                    raise ValueError(
                        f"{expression_id}/{locale}/sentence: '{target_word}'가 "
                        f"문장에 {len(occurrences)}번 나와 모호하다(ambiguous) — "
                        f"word-N 형식으로 위치를 지정하라"
                    )
                for word in occurrences:
                    if "accentContrast" in word:
                        del word["accentContrast"]
                        removed += 1
        reference_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        remaining = sum(
            1 for entry in entries for word in entry["words"]
            if "accentContrast" in word
        )
        print(f"{reference_path.name}: 제거 {removed} · 잔여 대조 {remaining}")
        removed_total += removed
    targets_total = len(word_targets) + len(sentence_targets)
    print(f"총 제거 {removed_total} (실패 인스턴스 {targets_total})")


def main() -> None:
    parser = argparse.ArgumentParser(description="verify-accent 실패 대조 프루닝")
    parser.add_argument("--problems", required=True, type=Path)
    parser.add_argument("--reference-dir", required=True, type=Path)
    args = parser.parse_args()
    prune(args.problems, args.reference_dir)


if __name__ == "__main__":
    main()
