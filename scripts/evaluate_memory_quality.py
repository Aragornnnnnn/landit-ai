# LAN-454 합성 발화를 실제 LLM으로 평가하며 unittest에서는 네트워크를 호출하지 않는다.
import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.free_talk.application.memory_service import (
    EXTRACTOR_VERSION,
    _candidate_system_prompt,
    _candidate_user_prompt,
    _validated_candidate_drafts,
)
from app.free_talk.llm.json_completion import request_json_completion
from app.models.free_talk import MemoryCandidatesRequest


def build_payload(case: dict) -> MemoryCandidatesRequest:
    return MemoryCandidatesRequest.model_validate({
        "sessionId": 1, "characterId": "chloe", "targetLocale": "EN",
        "baseLocale": "KR", "timezone": case.get("timezone", "Asia/Seoul"),
        "conversationHistory": [
            {"messageId": index, "turnNumber": index, "role": role,
             "content": text, "occurredAt": case.get("occurredAt", "2026-09-07T10:00:00+09:00")}
            for index, (role, text) in enumerate(case["turns"], 1)
        ],
    })


def acceptance_errors(case: dict, candidates: list) -> list[str]:
    errors = []
    if not case["min"] <= len(candidates) <= case["max"]:
        errors.append("candidate_count")
    if any(candidate.memoryType.value not in case["types"] for candidate in candidates):
        errors.append("memory_type")
    content = " ".join(candidate.content for candidate in candidates).casefold()
    content = re.sub(
        r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일",
        lambda match: "-".join(f"{int(part):02d}" for part in match.groups()), content,
    )
    if any(word.casefold() not in content for word in case.get("required", [])):
        errors.append("missing_detail")
    if any(word.casefold() in content for word in case.get("forbidden", [])):
        errors.append("unsupported_detail")
    if "validFrom" in case and any(
        candidate.validFrom != datetime.fromisoformat(case["validFrom"])
        for candidate in candidates
    ):
        errors.append("event_time")
    return errors


def evaluate(case: dict, settings: Settings, prompt: str) -> dict:
    payload = build_payload(case)
    try:
        raw = request_json_completion(
            settings=settings, system_prompt=prompt,
            user_prompt=_candidate_user_prompt(payload),
        )
        candidates = _validated_candidate_drafts(raw, payload)
        return {"case": case["id"], "errors": acceptance_errors(case, candidates),
                "candidates": [item.model_dump(mode="json", exclude={"embedding"})
                               for item in candidates]}
    except Exception as exc:
        return {"case": case["id"], "errors": [type(exc).__name__]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.runs <= 3:
        parser.error("runs must be between 1 and 3")
    cases = json.loads(args.cases.read_text())
    settings = Settings(_env_file=None)
    prompt = _candidate_system_prompt()
    report = {"at": datetime.now(UTC).isoformat(), "model": settings.openrouter_model,
              "extractorVersion": EXTRACTOR_VERSION,
              "promptSha256": hashlib.sha256(prompt.encode()).hexdigest(),
              "casesSha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
              "results": []}
    for run in range(args.runs):
        for case in cases:
            result = evaluate(case, settings, prompt) | {"run": run + 1}
            report["results"].append(result)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(f"run={run + 1} case={case['id']} errors={result['errors']}", flush=True)
    return int(any(result["errors"] for result in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
