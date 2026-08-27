# LAN-373 발음 판정 회귀 평가 — 골든 셋으로 판정 성능·지연·확장 필드를 측정한다.
#
# LAN-209 PoC가 확정한 성능(정확일치 24/24, 오탐 0, 지연 p50 4.5초)이 확장 프롬프트
# 도입 후에도 유지되는지 검증한다. 실제 서비스 코드(app.pronunciation.llm.compare)를
# 그대로 호출하므로 프롬프트·모델 설정 변경이 바로 반영된다.
#
# 사용법:
#   .venv/bin/python scripts/eval_pronunciation_golden.py \
#       --manifest docs/tasks/LAN-209/poc_manifest_v2.json --runs 2
import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.core.openai_client import create_openai_client  # noqa: E402
from app.pronunciation.llm.compare import judge_pronunciation  # noqa: E402

# 판정 유형(SOUND/STRESS)은 골든 셋 expected 표기와 동일하다
_PUNCTUATION = re.compile(r"[^a-z']")


def normalize(word: str) -> str:
    return _PUNCTUATION.sub("", word.lower())


def score(detected: set, expected: set) -> dict:
    return {
        "detected": sorted(f"{w}:{t}" for w, t in detected),
        "missed": sorted(f"{w}:{t}" for w, t in expected - detected),
        "falsePositives": sorted(f"{w}:{t}" for w, t in detected - expected),
        "exactMatch": detected == expected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN-373 발음 판정 회귀 평가")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/tasks/LAN-209/poc_manifest_v2.json"),
    )
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument(
        "--base-prompt",
        action="store_true",
        help="확장 필드 없이 PoC 검증본 프롬프트로 평가한다 (폴백 스펙 확인용)",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("docs/tasks/LAN-373"))
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    settings = Settings()
    client = create_openai_client(settings)
    extended = not args.base_prompt
    results = []

    for sentence in manifest["sentences"]:
        reference_wav = Path(sentence["tts"]).read_bytes()
        for sample in sentence["samples"]:
            user_wav = Path(sample["audio"]).read_bytes()
            expected = {
                (normalize(item["word"]), item["type"]) for item in sample["expected"]
            }
            for run in range(1, args.runs + 1):
                start = time.time()
                try:
                    differences = judge_pronunciation(
                        client,
                        settings,
                        reference_wav=reference_wav,
                        user_wav=user_wav,
                        extended=extended,
                    )
                    detected = {(normalize(d.word), d.type) for d in differences}
                    row = {
                        "label": sample["label"],
                        "run": run,
                        "latency": round(time.time() - start, 1),
                        "fields": [
                            {
                                "word": d.word,
                                "type": d.type,
                                "userHeard": d.user_heard,
                                "targetSpan": d.target_span,
                                "userSpan": d.user_span,
                                "stressIndex": d.stress_index,
                            }
                            for d in differences
                        ],
                        **score(detected, expected),
                    }
                except Exception as error:  # noqa: BLE001 — 실패도 기록 대상이다
                    row = {
                        "label": sample["label"],
                        "run": run,
                        "error": f"{type(error).__name__}: {str(error)[:200]}",
                    }
                results.append(row)
                flag = (
                    "ERR"
                    if "error" in row
                    else ("O" if row["exactMatch"] else "X")
                )
                print(
                    f"{sample['label']:14s} run{run} [{flag}] "
                    f"{row.get('latency', '-'):>5}s "
                    f"det={row.get('detected')} miss={row.get('missed')} "
                    f"fp={row.get('falsePositives')}",
                    flush=True,
                )

    _report(results, extended, args.out_dir)


def _report(results: list[dict], extended: bool, out_dir: Path) -> None:
    ok = [row for row in results if "error" not in row]
    latencies = sorted(row["latency"] for row in ok)
    exact = sum(row["exactMatch"] for row in ok)
    false_positive_runs = sum(bool(row["falsePositives"]) for row in ok)

    print("\n===== 요약 =====")
    print(f"프롬프트: {'확장' if extended else 'PoC 검증본'}")
    # 분모는 에러 run 포함 전체 — 에러 run을 빼면 성적이 실제보다 좋아 보인다
    print(f"정확일치 {exact}/{len(results)} · 오탐 run {false_positive_runs} · "
          f"에러 {len(results) - len(ok)}")
    if latencies:
        print(f"지연 p50={statistics.median(latencies):.1f}s max={latencies[-1]}s")

    if extended:
        flagged = [field for row in ok for field in row["fields"]]
        filled = sum(1 for field in flagged if field["userHeard"])
        print(f"확장 필드: 지적 {len(flagged)}건 중 userHeard {filled}건 채워짐")

    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "extended" if extended else "base"
    path = out_dir / f"golden_{timestamp}_{suffix}.json"
    path.write_text(
        json.dumps({"extended": extended, "results": results}, ensure_ascii=False,
                   indent=2),
        encoding="utf-8",
    )
    print(f"\n결과 저장: {path}")


if __name__ == "__main__":
    main()
