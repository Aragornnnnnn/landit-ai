# LAN-209 발음 판정 PoC — Gemini 2.5 Flash가 기준 데이터 대비 음소/강세 오류를
# 일관되게 감지하는지 검증하는 스크립트. 골든 셋(의도적 오발음 녹음)을 여러 번
# 판정시켜 기대 오류와의 일치율·반복 일관성을 측정한다.
#
# 사용법:
#   .venv/bin/python scripts/poc_pronunciation.py \
#       --manifest docs/tasks/LAN-209/poc_manifest.json --runs 3
import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.openai_client import create_openai_client  # noqa: E402

DEFAULT_MODEL = "google/gemini-2.5-flash"
AUDIO_FORMATS = {".wav": "wav", ".mp3": "mp3"}

PROMPT_TEMPLATE = """You are an English pronunciation assessor for Korean learners.

The learner read this sentence aloud:
"{sentence}"

Reference pronunciation (authoritative — judge ONLY against this):
{reference}

Work in two steps.

STEP 1 — PERCEPTION. Listen carefully and, for every reference word, write down
what you actually heard as a respelling in the same style as the reference
"syllables" (put it in the "heard" field). Also note which syllable carried the
strongest emphasis ("heardStressIndex", -1 if none stood out). Describe only the
acoustic evidence; do not compare with the reference yet.

STEP 2 — VERDICT. Compare your STEP 1 perception against the reference.
Detect exactly two error types:
- PHONEME: a phoneme clearly sounded like a DIFFERENT phoneme (e.g. TH -> S)
- STRESS: emphasis clearly fell on a different syllable than stressIndex.
  Words with stressIndex -1 can NEVER have a STRESS error.

Strict rules for STEP 2:
- Most learners pronounce most words correctly. A typical sentence has zero or
  one wrong word. Flag a word ONLY if the deviation is unmistakable.
- Slight accent, speed, loudness or recording-quality differences are NOT
  errors. If you are less than fully certain, set ok=true.
- At most one error per word (the most salient one).
- errorTargetSpan / errorUserSpan: the substring of the reference display and
  of your "heard" respelling that differ (e.g. "th" / "ss").

Respond with JSON only, no markdown fences, using exactly this schema:
{{
  "overallScore": <int 0-100, sentence-level pronunciation accuracy>,
  "words": [
    {{"word": "<word>", "order": <int>, "heard": "<respelling>",
      "heardStressIndex": <int>, "ok": true}},
    {{"word": "<word>", "order": <int>, "heard": "<respelling>",
      "heardStressIndex": <int>, "ok": false,
      "errorType": "PHONEME", "expectedPhoneme": "<ARPABET>",
      "actualPhoneme": "<ARPABET>", "userDisplay": "<respelling>",
      "errorTargetSpan": "<substring>", "errorUserSpan": "<substring>"}},
    {{"word": "<word>", "order": <int>, "heard": "<respelling>",
      "heardStressIndex": <int>, "ok": false,
      "errorType": "STRESS", "userStressIndex": <int>}}
  ]
}}
Every reference word must appear exactly once, in order."""


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for key in ("sentence", "reference", "samples"):
        if key not in manifest:
            raise ValueError(f"manifest에 '{key}'가 없습니다.")
    return manifest


def encode_audio(path: Path) -> tuple[str, str]:
    audio_format = AUDIO_FORMATS.get(path.suffix.lower())
    if audio_format is None:
        raise ValueError(f"{path.name}: wav/mp3만 지원합니다. (m4a는 wav로 변환 필요)")
    return base64.b64encode(path.read_bytes()).decode("ascii"), audio_format


def analyze(client, model: str, manifest: dict, audio_path: Path) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        sentence=manifest["sentence"],
        reference=json.dumps(manifest["reference"], ensure_ascii=False, indent=2),
    )
    data, audio_format = encode_audio(audio_path)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "input_audio",
                    "input_audio": {"data": data, "format": audio_format},
                },
            ],
        }
    ]
    last_error: Exception | None = None
    for _ in range(2):  # JSON 파싱 실패 시 1회 재시도
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0.0, max_tokens=8000
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            last_error = RuntimeError("빈 응답 (thinking 토큰 소진 가능성)")
            continue
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            last_error = error
    raise RuntimeError(f"JSON 파싱 2회 실패: {last_error}")


def detected_errors(result: dict) -> set[tuple[str, str]]:
    return {
        (word["word"].lower(), word.get("errorType", "?"))
        for word in result.get("words", [])
        if not word.get("ok", True)
    }


def evaluate_sample(client, model: str, manifest: dict, sample: dict, runs: int) -> dict:
    audio_path = Path(sample["audio"])
    expected = {(e["word"].lower(), e["errorType"]) for e in sample.get("expected", [])}
    run_results = []
    for run_index in range(1, runs + 1):
        result = analyze(client, model, manifest, audio_path)
        detected = detected_errors(result)
        run_results.append(
            {
                "run": run_index,
                "overallScore": result.get("overallScore"),
                "detected": sorted(f"{w}:{t}" for w, t in detected),
                "missed": sorted(f"{w}:{t}" for w, t in expected - detected),
                "falsePositives": sorted(f"{w}:{t}" for w, t in detected - expected),
                "exactMatch": detected == expected,
                "raw": result,
            }
        )
        print(
            f"  run {run_index}: score={result.get('overallScore')} "
            f"detected={run_results[-1]['detected']} "
            f"missed={run_results[-1]['missed']} "
            f"falsePositives={run_results[-1]['falsePositives']}"
        )
    detected_sets = [tuple(r["detected"]) for r in run_results]
    return {
        "label": sample.get("label", audio_path.stem),
        "audio": str(audio_path),
        "expected": sorted(f"{w}:{t}" for w, t in expected),
        "exactMatchRate": sum(r["exactMatch"] for r in run_results) / runs,
        "consistent": len(set(detected_sets)) == 1,
        "runs": run_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN-209 발음 판정 PoC")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=3, help="샘플당 반복 판정 횟수")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("docs/tasks/LAN-209/poc_results")
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    client = create_openai_client()

    summary = []
    for sample in manifest["samples"]:
        print(f"\n=== {sample.get('label', sample['audio'])} ===")
        summary.append(evaluate_sample(client, args.model, manifest, sample, args.runs))

    print("\n===== 요약 =====")
    for item in summary:
        print(
            f"{item['label']}: expected={item['expected']} "
            f"정확일치율={item['exactMatchRate']:.0%} "
            f"반복일관성={'O' if item['consistent'] else 'X'}"
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out_dir / f"{timestamp}_{args.model.replace('/', '_')}.json"
    out_path.write_text(
        json.dumps(
            {"model": args.model, "runs": args.runs, "samples": summary},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
