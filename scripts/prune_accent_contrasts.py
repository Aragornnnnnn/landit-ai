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

_PROBLEM = re.compile(r"^(\d+)/(EN_\w+)/\S+: '(.*?)' (?:sounded|could)")


def prune(problems_path: Path, reference_dir: Path) -> None:
    # (expressionId, locale, 단어소문자) → 제거 대상
    targets: set[tuple[int, str, str]] = set()
    for line in problems_path.read_text(encoding="utf-8").splitlines():
        match = _PROBLEM.match(line.strip())
        if match:
            targets.add(
                (int(match.group(1)), match.group(2), match.group(3).lower())
            )

    removed_total = 0
    for reference_path in sorted(reference_dir.glob("reference_EN_*.json")):
        if "review" in reference_path.name:
            continue
        entries = json.loads(reference_path.read_text(encoding="utf-8"))
        removed = 0
        for entry in entries:
            locale = entry["accentLocale"]
            for word in entry["words"]:
                key = (entry["expressionId"], locale, word["word"].lower())
                if key in targets and "accentContrast" in word:
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
    print(f"총 제거 {removed_total} (실패 인스턴스 {len(targets)})")


def main() -> None:
    parser = argparse.ArgumentParser(description="verify-accent 실패 대조 프루닝")
    parser.add_argument("--problems", required=True, type=Path)
    parser.add_argument("--reference-dir", required=True, type=Path)
    args = parser.parse_args()
    prune(args.problems, args.reference_dir)


if __name__ == "__main__":
    main()
