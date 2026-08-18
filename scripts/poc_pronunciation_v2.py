# LAN-209 발음 판정 PoC v2 — 두 가지 유력 방식을 확장 골든 셋으로 검증한다.
#   transcribe: 자유 전사(기준 미제공) 후 서버측 단어 비교 → 음소 오류 감지
#   compare   : 원어민 TTS 참조 오디오와 학습자 오디오를 직접 대조 → 음소+강세 감지
#
# 사용법:
#   .venv/bin/python scripts/poc_pronunciation_v2.py \
#       --manifest docs/tasks/LAN-209/poc_manifest_v2.json --runs 2
import argparse
import base64
import difflib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.openai_client import create_openai_client  # noqa: E402

DEFAULT_MODEL = "google/gemini-3.5-flash"

TRANSCRIBE_PROMPT = (
    "Transcribe EXACTLY what you hear. If a word is mispronounced, "
    "write it phonetically as pronounced (e.g. 'nussing' not 'nothing'). "
    "Do not correct anything. Output only the transcription."
)

COMPARE_PROMPT = """You will hear two audio clips. Audio 1 is a native speaker
reading a sentence (reference). Audio 2 is a learner attempting the same sentence.

Compare them word by word, judging ONLY from what you hear in the audio.

Completely ignore: voice, gender, pitch, speed, volume, recording quality,
contractions or linking (e.g. "there is" vs "there's"), and minor accent
coloration. These are NEVER differences.

Report a word ONLY when:
- SOUND: a phoneme is clearly substituted with a different phoneme
  (e.g. "th" pronounced as "s", "r" pronounced as "l"), or
- STRESS: within that word, the emphasized syllable is clearly different
  from the reference.

Typical learners get most words right — expect 0 or 1 flagged words.
If you are not certain, do not flag the word.

Respond with JSON only, no markdown fences:
{"differences": [{"word": "<word>", "type": "SOUND", "note": "<short>"},
                 {"word": "<word>", "type": "STRESS", "note": "<short>"}]}
If there are no clear differences: {"differences": []}"""


def b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def audio_part(data: str) -> dict:
    return {"type": "input_audio", "input_audio": {"data": data, "format": "wav"}}


def call(client, model: str, content: list) -> tuple[str, float]:
    start = time.time()
    response = client.chat.completions.create(
        model=model,
        temperature=0.0,
        max_tokens=4000,
        messages=[{"role": "user", "content": content}],
        # 지연 최적화 실험 결과 채택: 정확도 손실 없이 p50 5.7s → 4.5s
        extra_body={"reasoning": {"effort": "low"}},
    )
    text = (response.choices[0].message.content or "").strip()
    return text, time.time() - start


def words_of(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def transcribe_detect(sentence: str, transcription: str) -> set[tuple[str, str]]:
    expected_words = words_of(sentence)
    heard_words = words_of(transcription)
    matcher = difflib.SequenceMatcher(a=expected_words, b=heard_words)
    detected: set[tuple[str, str]] = set()
    for op, a1, a2, _, _ in matcher.get_opcodes():
        if op in ("replace", "delete"):
            for word in expected_words[a1:a2]:
                detected.add((word, "SOUND"))
    return detected


def parse_compare(text: str) -> set[tuple[str, str]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    payload = json.loads(cleaned)
    return {
        (d["word"].strip().lower().strip(".,!?"), d["type"])
        for d in payload.get("differences", [])
    }


def score(detected: set, expected: set) -> dict:
    return {
        "detected": sorted(f"{w}:{t}" for w, t in detected),
        "missed": sorted(f"{w}:{t}" for w, t in expected - detected),
        "falsePositives": sorted(f"{w}:{t}" for w, t in detected - expected),
        "exactMatch": detected == expected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN-209 발음 판정 PoC v2")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--modes", default="transcribe,compare")
    parser.add_argument(
        "--out-dir", type=Path, default=Path("docs/tasks/LAN-209/poc_results")
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    modes = args.modes.split(",")
    client = create_openai_client()
    results = []

    for sentence in manifest["sentences"]:
        tts_data = b64(sentence["tts"]) if "compare" in modes else None
        for sample in sentence["samples"]:
            expected_all = {(e["word"].lower(), e["type"]) for e in sample["expected"]}
            sample_data = b64(sample["audio"])
            for mode in modes:
                # transcribe 모드는 강세를 원리상 감지할 수 없으므로 SOUND만 채점
                expected = (
                    {(w, t) for w, t in expected_all if t == "SOUND"}
                    if mode == "transcribe"
                    else expected_all
                )
                for run in range(1, args.runs + 1):
                    try:
                        if mode == "transcribe":
                            text, elapsed = call(
                                client,
                                args.model,
                                [
                                    {"type": "text", "text": TRANSCRIBE_PROMPT},
                                    audio_part(sample_data),
                                ],
                            )
                            detected = transcribe_detect(sentence["text"], text)
                        else:
                            text, elapsed = call(
                                client,
                                args.model,
                                [
                                    {"type": "text", "text": COMPARE_PROMPT},
                                    audio_part(tts_data),
                                    audio_part(sample_data),
                                ],
                            )
                            detected = parse_compare(text)
                        row = {
                            "label": sample["label"],
                            "mode": mode,
                            "run": run,
                            "latency": round(elapsed, 1),
                            "raw": text,
                            **score(detected, expected),
                        }
                    except Exception as error:  # noqa: BLE001 — PoC: 오류도 데이터
                        row = {
                            "label": sample["label"],
                            "mode": mode,
                            "run": run,
                            "error": str(error)[:200],
                        }
                    results.append(row)
                    flag = (
                        "ERR"
                        if "error" in row
                        else ("O" if row["exactMatch"] else "X")
                    )
                    print(
                        f"{sample['label']:12s} {mode:10s} run{run} "
                        f"[{flag}] {row.get('latency', '-'):>5}s "
                        f"det={row.get('detected')} miss={row.get('missed')} "
                        f"fp={row.get('falsePositives')}",
                        flush=True,
                    )

    print("\n===== 요약 =====")
    for mode in modes:
        rows = [r for r in results if r["mode"] == mode and "error" not in r]
        errors = [r for r in results if r["mode"] == mode and "error" in r]
        exact = sum(r["exactMatch"] for r in rows)
        fp_runs = sum(bool(r["falsePositives"]) for r in rows)
        lat = sorted(r["latency"] for r in rows)
        print(
            f"{mode:10s} 정확일치 {exact}/{len(rows)} · 오탐 run {fp_runs} · "
            f"지연 p50={lat[len(lat)//2] if lat else '-'}s "
            f"max={lat[-1] if lat else '-'}s · 에러 {len(errors)}"
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out_dir / f"v2_{timestamp}_{args.model.replace('/', '_')}.json"
    out_path.write_text(
        json.dumps(
            {"model": args.model, "runs": args.runs, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
