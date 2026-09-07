# 시나리오 1 합성 대화의 제품 수준 평가와 블라인드 기준 평가를 실행한다.
import argparse
import hashlib
import json
import statistics
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter

from app.conversation.application import next_message_service
from app.conversation.application.next_message_service import (
    generate_session_level_assessment,
)
from app.conversation.application.session_assessment_rubric import (
    SESSION_LEVEL_ASSESSMENT_RUBRIC,
)
from app.core.config import Settings
from app.core.openai_client import create_openai_client
from app.models.conversation import SessionLevelAssessmentRequest


QUESTIONS = [
    {
        "text": (
            "Hey! I'm Marco, an exchange student from Spain. Nice to meet you! "
            "Can you introduce yourself a little? — What do you do, and what do "
            "you like to do in your free time?"
        ),
        "translation": (
            "안녕! 난 마르코고, 스페인에서 온 교환학생이야. 만나서 반가워! "
            "자기소개를 간단히 해줄래? — 어떤 일을 하고, 여가 시간에는 뭘 즐겨 해?"
        ),
        "demand": "MEDIUM",
        "required": [
            "Describe what you do.",
            "State what you like to do in your free time.",
        ],
    },
    {
        "text": "So, have you done anything fun or memorable lately?",
        "translation": "그럼, 최근에 했던 즐겁거나 기억에 남는 일 있어?",
        "demand": "MEDIUM",
        "required": [
            "Share a recent fun or memorable experience, or state that you have not "
            "had one."
        ],
    },
    {
        "text": (
            "If you could travel anywhere in the world next year, where would you "
            "go? And why there?"
        ),
        "translation": "내년에 세계 어디든 여행할 수 있다면, 어디로 가고 싶어? 그 이유는 뭐야?",
        "demand": "HIGH",
        "required": [
            "Name a destination you would choose for next year.",
            "Explain why you would choose that destination.",
        ],
    },
    {
        "text": (
            "Some of my friends say traveling alone is way better than traveling "
            "with friends. I'm not so sure though. What do you think?"
        ),
        "translation": (
            "내 친구들 중엔 혼자 여행하는 게 친구랑 가는 것보다 훨씬 낫다는 "
            "애들이 있거든. 난 잘 모르겠던데. 넌 어떻게 생각해?"
        ),
        "demand": "HIGH",
        "required": [
            "Express your view on traveling alone compared with traveling with "
            "friends."
        ],
    },
]

SCENARIO = {
    "scenarioId": 1,
    "title": "처음 만난 교환학생과 대화하기",
    "briefing": (
        "스페인에서 온 교환학생 Marco와 서로를 소개하고 여행에 관해 대화합니다."
    ),
    "conversationGoal": "자신의 일상과 경험을 설명하고 여행에 관한 의견을 나눕니다.",
    "counterpartRole": "exchange student Marco",
    "serviceAudience": "KOREAN_LEARNER",
}

DOMAIN_NAMES = [
    "situationPerformance",
    "grammar",
    "vocabulary",
    "discourse",
    "interactionPragmatics",
]
DEMAND_WEIGHTS = {"MEDIUM": Decimal("0.70"), "HIGH": Decimal("1.00")}
DOMAIN_WEIGHTS = {
    "situationPerformance": Decimal("0.30"),
    "grammar": Decimal("0.20"),
    "vocabulary": Decimal("0.20"),
    "discourse": Decimal("0.15"),
    "interactionPragmatics": Decimal("0.15"),
}


@dataclass
class UsageRecorder:
    calls: list[dict[str, Any]]
    case_id: str = ""
    phase: str = ""

    def wrap(self, client: OpenAI) -> Any:
        recorder = self

        class RecordingCompletions:
            def create(self, **kwargs: Any) -> Any:
                started = time.perf_counter()
                completion = client.chat.completions.create(**kwargs)
                usage = completion.usage.model_dump() if completion.usage else {}
                recorder.calls.append(
                    {
                        "caseId": recorder.case_id,
                        "phase": recorder.phase,
                        "model": kwargs.get("model"),
                        "requestId": completion.id,
                        "finishReason": completion.choices[0].finish_reason,
                        "latencySeconds": round(time.perf_counter() - started, 3),
                        "usage": usage,
                        "rawResponse": completion.choices[0].message.content,
                    }
                )
                return completion

        class RecordingChat:
            completions = RecordingCompletions()

        class RecordingClient:
            chat = RecordingChat()

        return RecordingClient()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("reference", "product", "score"))
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--repeat-runs", type=int, default=3)
    parser.add_argument("--reference-model", default="google/gemini-3.5-flash")
    parser.add_argument("--product-model", default="openai/gpt-5.4-mini")
    parser.add_argument("--aws-profile", default="landit")
    parser.add_argument("--ssm-key", default="/landit/develop/OPENROUTER_API_KEY")
    return parser.parse_args()


class BlindCase(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    caseId: str = Field(min_length=1)
    split: Literal["development", "holdout", "edge"]
    repeat: bool
    answers: list[str] = Field(min_length=4, max_length=4)


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = TypeAdapter(list[BlindCase]).validate_json(path.read_text(encoding="utf-8"))
    if len(cases) != 40:
        raise ValueError("blind dataset must contain 40 four-answer conversations")
    if len({case.caseId for case in cases}) != len(cases):
        raise ValueError("blind dataset caseId must be unique")
    return [case.model_dump() for case in cases]


def api_key(profile: str, parameter: str) -> str:
    result = subprocess.run(
        [
            "aws",
            "--profile",
            profile,
            "ssm",
            "get-parameter",
            "--name",
            parameter,
            "--with-decryption",
            "--query",
            "Parameter.Value",
            "--output",
            "text",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not value:
        raise RuntimeError("OpenRouter key is blank")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(args: argparse.Namespace) -> None:
    manifest_path = args.output_dir / "manifest.json"
    repository = Path(__file__).resolve().parents[1]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    prompt = next_message_service._session_level_assessment_system_prompt()
    manifest = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "aiRevision": revision,
        "bePolicyScope": "local formula replica, not BE HTTP or database",
        "datasetSha256": file_sha256(args.cases),
        "rubricSha256": file_sha256(
            repository / "app/conversation/application/session_assessment_rubric.py"
        ),
        "productEndpoint": "/api/v1/conversation/session-level-assessment",
        "measurementScope": "session-level-assessment only",
        "sessionLevelAssessmentPromptSha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "coreRetryPromptSha256": hashlib.sha256(
            next_message_service._session_level_assessment_retry_system_prompt().encode()
        ).hexdigest(),
        "questionSha256": hashlib.sha256(
            json.dumps(QUESTIONS, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "productModel": args.product_model,
        "referenceModel": args.reference_model,
        "referencePromptSha256": hashlib.sha256(
            reference_prompt({"answers": [""] * 4}).encode()
        ).hexdigest(),
        "assessmentVersion": "text-level-v1.1",
    }
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        changed = [
            key for key, value in manifest.items()
            if key not in {"createdAt", "aiRevision"}
            and previous.get(key) != value
        ]
        if changed:
            raise ValueError("blind manifest settings changed: " + ", ".join(changed))
        return
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def reference_prompt(case: dict[str, Any]) -> str:
    visible = [
        {"question": question["text"], "answer": answer}
        for question, answer in zip(QUESTIONS, case["answers"], strict=True)
    ]
    return (
        "Independently assess this Korean learner's English text. You do not know "
        "the author's intended level or any product result.\n"
        f"{SESSION_LEVEL_ASSESSMENT_RUBRIC}\n\n"
        "Return only JSON with assessable (boolean), allowedLevelRange ([min,max]), and notes. "
        "Also return messages in input order; each message must contain "
        "taskPerformance and all five domains. "
        "Each domain contains level 1-5 or null, evidenceStatus, and an exact "
        "evidenceExcerpt or null. The allowed range is your independent session-level "
        "judgment, not a simple average.\n\n"
        f"Conversation JSON:\n{json.dumps(visible, ensure_ascii=False)}"
    )


def parse_reference(raw: str, case: dict[str, Any]) -> dict[str, Any]:
    try:
        value = next_message_service._parse_json_object(raw)
    except next_message_service.AiResponseInvalidError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(raw[start : end + 1])
    if not isinstance(value.get("assessable"), bool):
        raise ValueError("reference assessable must be boolean")
    allowed = value.get("allowedLevelRange")
    if (
        not isinstance(allowed, list)
        or len(allowed) != 2
        or any(type(level) is not int or not 1 <= level <= 5 for level in allowed)
        or allowed[0] > allowed[1]
    ):
        raise ValueError("reference allowedLevelRange is invalid")
    messages = value.get("messages")
    if not isinstance(messages, list) or len(messages) != 4:
        raise ValueError("reference must contain four messages")
    for answer, message in zip(case["answers"], messages, strict=True):
        domains = message.get("domains") if isinstance(message, dict) else None
        if isinstance(message, dict) and domains is None and all(
            name in message for name in DOMAIN_NAMES
        ):
            domains = {name: message.pop(name) for name in DOMAIN_NAMES}
            message["domains"] = domains
        if not isinstance(domains, dict) or set(domains) != set(DOMAIN_NAMES):
            raise ValueError("reference domains are invalid")
        for domain in domains.values():
            if not isinstance(domain, dict):
                raise ValueError("reference domain must be an object")
            status = domain.get("evidenceStatus")
            level = domain.get("level")
            excerpt = domain.get("evidenceExcerpt")
            if status == "OBSERVED":
                if type(level) is not int or not 1 <= level <= 5:
                    raise ValueError("observed reference level is invalid")
                if not isinstance(excerpt, str) or excerpt not in answer:
                    raise ValueError("reference evidence is not an exact answer substring")
            elif status in {"NOT_OBSERVED", "INSUFFICIENT_EVIDENCE"}:
                if level is not None or excerpt is not None:
                    raise ValueError("unobserved reference must have null evidence")
            else:
                raise ValueError("reference evidenceStatus is invalid")
    return value


def run_reference(args: argparse.Namespace, cases: list[dict[str, Any]]) -> None:
    output = args.output_dir / "reference.jsonl"
    if output.exists():
        raise FileExistsError(f"reference output already exists: {output}")
    key = api_key(args.aws_profile, args.ssm_key)
    client = OpenAI(
        api_key=key,
        base_url="https://openrouter.ai/api/v1",
        timeout=60.0,
        max_retries=0,
    )
    for case in cases[: args.limit]:
        started = time.perf_counter()
        raw = ""
        try:
            completion = client.chat.completions.create(
                model=args.reference_model,
                temperature=0,
                max_tokens=4096,
                response_format={"type": "json_object"},
                extra_body={"reasoning": {"effort": "low"}},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an independent English speaking assessment "
                            "reference rater."
                        ),
                    },
                    {"role": "user", "content": reference_prompt(case)},
                ],
            )
            raw = completion.choices[0].message.content or ""
            parsed = parse_reference(raw, case)
            value = {
                "caseId": case["caseId"],
                "status": "SUCCESS",
                "reference": parsed,
                "model": args.reference_model,
                "requestId": completion.id,
                "latencySeconds": round(time.perf_counter() - started, 3),
                "usage": completion.usage.model_dump() if completion.usage else {},
            }
        except Exception as exc:
            value = {
                "caseId": case["caseId"],
                "status": "FAILED",
                "errorType": type(exc).__name__,
                "error": str(exc)[:300],
                "rawResponse": raw[:12000] or None,
                "latencySeconds": round(time.perf_counter() - started, 3),
            }
        append_jsonl(output, value)
        print(f"reference {case['caseId']} {value['status']}", flush=True)


def assessment_payload(session_id: int, case: dict[str, Any]) -> dict[str, Any]:
    messages = []
    for sequence, (question, answer) in enumerate(
        zip(QUESTIONS, case["answers"], strict=True), start=1
    ):
        messages.append(
            {
                "messageId": session_id * 10 + sequence,
                "evaluationContext": question["text"],
                "userMessage": answer,
                "responseDemand": question["demand"],
                "requiredElements": question["required"],
            }
        )
    return {
        "sessionId": session_id,
        "scenario": SCENARIO,
        "expectedMessageIds": [message["messageId"] for message in messages],
        "assessmentMessages": messages,
    }


def decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def be_policy(level_assessment: dict[str, Any] | None) -> dict[str, Any]:
    if not level_assessment:
        return {
            "source": "FALLBACK",
            "sufficientEvidence": False,
            "overallScore": None,
            "assessedLevel": None,
            "displayLevel": 3,
            "changeType": "NOT_APPLIED",
            "domains": {},
        }
    messages = level_assessment["core"]["messages"]
    total_weight = sum(DEMAND_WEIGHTS[question["demand"]] for question in QUESTIONS)
    domains: dict[str, Any] = {}
    for name in DOMAIN_NAMES:
        weighted = Decimal("0")
        observed_weight = Decimal("0")
        observed_count = 0
        for question, message in zip(QUESTIONS, messages, strict=True):
            domain = message["domains"][name]
            if domain["evidenceStatus"] == "OBSERVED" and domain["level"] is not None:
                weight = DEMAND_WEIGHTS[question["demand"]]
                weighted += weight * Decimal(domain["level"])
                observed_weight += weight
                observed_count += 1
        score = None if not observed_weight else weighted / observed_weight
        confidence = observed_weight / total_weight
        domains[name] = {
            "score": None if score is None else decimal(score),
            "confidence": decimal(confidence),
            "observedCount": observed_count,
            "sufficient": observed_count >= 2 and confidence >= Decimal("0.75"),
        }
    complete = all(domain["score"] is not None for domain in domains.values())
    overall = None
    if complete:
        overall = sum(
            Decimal(domains[name]["score"]) * weight
            for name, weight in DOMAIN_WEIGHTS.items()
        )
        overall = min(overall, Decimal("5.00"))
    sufficient = all(domain["sufficient"] for domain in domains.values())
    assessed = (
        None
        if overall is None
        else int(overall.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    )
    return {
        "source": "MODEL",
        "sufficientEvidence": sufficient,
        "overallScore": None if overall is None else decimal(overall),
        "assessedLevel": assessed,
        "displayLevel": assessed if assessed is not None else 3,
        "changeType": "INITIALIZED" if sufficient else "NOT_APPLIED",
        "appliedLevel": assessed if sufficient else None,
        "domains": domains,
    }


def product_runs(cases: list[dict[str, Any]], repeat_runs: int) -> list[tuple[dict[str, Any], int]]:
    runs = [(case, 1) for case in cases]
    for case in cases:
        if case["repeat"]:
            runs.extend((case, run) for run in range(2, repeat_runs + 1))
    return runs


def run_product(args: argparse.Namespace, cases: list[dict[str, Any]]) -> None:
    output = args.output_dir / "product.jsonl"
    if output.exists():
        raise FileExistsError(f"product output already exists: {output}")
    key = api_key(args.aws_profile, args.ssm_key)
    settings = Settings(
        llm_provider="openrouter",
        openrouter_api_key=SecretStr(key),
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_model=args.product_model,
    )
    recorder = UsageRecorder([])
    original_factory = next_message_service.create_openai_client
    next_message_service.create_openai_client = lambda resolved, **kwargs: recorder.wrap(
        create_openai_client(resolved, **kwargs)
    )
    try:
        for index, (case, run) in enumerate(
            product_runs(cases, args.repeat_runs)[: args.limit], start=1
        ):
            session_id = 438000 + index
            recorder.case_id = case["caseId"]
            recorder.phase = f"run-{run}"
            call_start = len(recorder.calls)
            started = time.perf_counter()
            try:
                response = generate_session_level_assessment(
                    SessionLevelAssessmentRequest.model_validate(
                        assessment_payload(session_id, case)
                    ),
                    settings,
                )
                assessment = (
                    response.levelAssessment.model_dump(mode="json")
                    if response.levelAssessment
                    else None
                )
                value = {
                    "caseId": case["caseId"],
                    "split": case["split"],
                    "run": run,
                    "status": "SUCCESS",
                    "levelAssessment": assessment,
                    "bePolicy": be_policy(assessment),
                    "latencySeconds": round(time.perf_counter() - started, 3),
                    "calls": recorder.calls[call_start:],
                }
            except Exception as exc:
                value = {
                    "caseId": case["caseId"],
                    "split": case["split"],
                    "run": run,
                    "status": "FAILED",
                    "errorType": type(exc).__name__,
                    "error": str(exc)[:300],
                    "latencySeconds": round(time.perf_counter() - started, 3),
                    "calls": recorder.calls[call_start:],
                }
            append_jsonl(output, value)
            print(
                f"product {index} {case['caseId']} run={run} {value['status']}",
                flush=True,
            )
    finally:
        next_message_service.create_openai_client = original_factory


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def reuse_reference(args: argparse.Namespace, cases: list[dict[str, Any]]) -> None:
    source = args.reference_dir / "reference.jsonl"
    target = args.output_dir / "reference.jsonl"
    if target.exists():
        raise FileExistsError(f"reference output already exists: {target}")
    previous = json.loads((args.reference_dir / "manifest.json").read_text())
    manifest_path = args.output_dir / "manifest.json"
    current = json.loads(manifest_path.read_text())
    for key in (
        "datasetSha256", "rubricSha256", "questionSha256",
        "referenceModel", "assessmentVersion",
    ):
        if previous.get(key) != current[key]:
            raise ValueError("reference manifest settings changed: " + key)
    if previous.get("referencePromptSha256", current["referencePromptSha256"]) != current["referencePromptSha256"]:
        raise ValueError("reference manifest settings changed: referencePromptSha256")
    rows = read_jsonl(source)
    by_id = {case["caseId"]: case for case in cases}
    if len(rows) != len(cases) or {row["caseId"] for row in rows} != set(by_id):
        raise ValueError("reference must contain every case exactly once")
    for row in rows:
        if row["status"] == "SUCCESS":
            if row["model"] != current["referenceModel"]:
                raise ValueError("reference row model changed")
            parse_reference(json.dumps(row["reference"]), by_id[row["caseId"]])
        elif row["status"] != "FAILED":
            raise ValueError("reference row status is invalid")
    current["referenceReuse"] = {
        "source": str(source.resolve()),
        "sha256": file_sha256(source),
        "sourceManifestSha256": file_sha256(args.reference_dir / "manifest.json"),
        "legacyPromptFingerprintMissing": "referencePromptSha256" not in previous,
    }
    target.write_bytes(source.read_bytes())
    manifest_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n")


def distance_to_range(level: int | None, allowed: list[int]) -> int | None:
    if level is None:
        return None
    low, high = allowed
    return low - level if level < low else level - high if level > high else 0


def score(args: argparse.Namespace, cases: list[dict[str, Any]]) -> None:
    references = {
        row["caseId"]: row
        for row in read_jsonl(args.output_dir / "reference.jsonl")
        if row["status"] == "SUCCESS"
    }
    products = read_jsonl(args.output_dir / "product.jsonl")
    primary = [row for row in products if row["run"] == 1]
    product_failures = [row for row in products if row["status"] != "SUCCESS"]
    missing_assessments = [
        row
        for row in products
        if row["status"] == "SUCCESS" and row.get("levelAssessment") is None
    ]
    comparable = []
    for row in primary:
        reference = references.get(row["caseId"])
        if (
            row["status"] != "SUCCESS"
            or row.get("levelAssessment") is None
            or not reference
        ):
            continue
        allowed = reference["reference"].get("allowedLevelRange")
        if reference["reference"].get("assessable") and allowed:
            distance = distance_to_range(row["bePolicy"]["assessedLevel"], allowed)
            comparable.append({"row": row, "distance": distance})
    holdout = [item for item in comparable if item["row"]["split"] == "holdout"]
    repeated: dict[str, list[dict[str, Any]]] = {}
    for row in products:
        if row["run"] > 1 or any(
            case["caseId"] == row["caseId"] and case["repeat"] for case in cases
        ):
            repeated.setdefault(row["caseId"], []).append(row)
    repeat_ranges = []
    for case_id, rows in repeated.items():
        levels = [
            row.get("bePolicy", {}).get("assessedLevel")
            for row in rows
            if row["status"] == "SUCCESS"
            and row.get("bePolicy", {}).get("assessedLevel") is not None
        ]
        repeat_ranges.append(
            {
                "caseId": case_id,
                "levels": levels,
                "range": max(levels) - min(levels) if levels else None,
                "initialized": [
                    row.get("bePolicy", {}).get("changeType") == "INITIALIZED"
                    for row in rows
                    if row["status"] == "SUCCESS"
                ],
            }
        )
    calls = [call for row in products for call in row.get("calls", [])]
    finish_reasons: dict[str, int] = {}
    for call in calls:
        reason = call.get("finishReason") or "UNKNOWN"
        finish_reasons[reason] = finish_reasons.get(reason, 0) + 1
    reference_rows = read_jsonl(args.output_dir / "reference.jsonl")
    reference_usage = [row.get("usage", {}) for row in reference_rows]
    tokens = {
        "prompt": sum(call.get("usage", {}).get("prompt_tokens", 0) or 0 for call in calls),
        "completion": sum(
            call.get("usage", {}).get("completion_tokens", 0) or 0 for call in calls
        ),
    }
    product_cost = sum(
        Decimal(str(call.get("usage", {}).get("cost", 0) or 0)) for call in calls
    )
    reference_cost = sum(
        Decimal(str(usage.get("cost", 0) or 0)) for usage in reference_usage
    )
    manifest_path = args.output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    reused_reference = manifest.get("referenceReuse")
    if reused_reference and file_sha256(args.output_dir / "reference.jsonl") != reused_reference["sha256"]:
        raise ValueError("reused reference file changed")
    new_reference_cost = Decimal("0") if reused_reference else reference_cost
    domain_stats = {}
    for name in DOMAIN_NAMES:
        pairs = []
        product_missing = 0
        reference_missing = 0
        for row in primary:
            reference = references.get(row["caseId"])
            if (
                row["status"] != "SUCCESS"
                or row.get("levelAssessment") is None
                or not reference
            ):
                continue
            product_messages = row["levelAssessment"]["core"]["messages"]
            reference_messages = reference["reference"]["messages"]
            for product_message, reference_message in zip(
                product_messages, reference_messages, strict=True
            ):
                product_domain = product_message["domains"][name]
                reference_domain = reference_message["domains"][name]
                product_level = product_domain["level"]
                reference_level = reference_domain["level"]
                if reference_level is not None and product_level is None:
                    product_missing += 1
                if reference_level is None and product_level is not None:
                    reference_missing += 1
                if product_level is not None and reference_level is not None:
                    pairs.append(abs(product_level - reference_level))
        domain_stats[name] = {
            "observedPairs": len(pairs),
            "exact": sum(distance == 0 for distance in pairs),
            "withinOne": sum(distance <= 1 for distance in pairs),
            "productMissingWhenReferenceObserved": product_missing,
            "productObservedWhenReferenceMissing": reference_missing,
        }
    failure_reasons: dict[str, int] = {}
    for row in products:
        if row["status"] == "SUCCESS":
            continue
        reason = row.get("errorType", "UNKNOWN")
        raw = row.get("calls", [{}])[-1].get("rawResponse") if row.get("calls") else None
        if raw:
            try:
                json.loads(raw)
                reason += ":VALID_JSON_REJECTED"
            except json.JSONDecodeError:
                reason += ":INVALID_JSON"
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
    if missing_assessments:
        failure_reasons["MISSING_LEVEL_ASSESSMENT"] = len(missing_assessments)
    summary = {
        "dataset": {
            "total": len(cases),
            "splits": {
                split: sum(case["split"] == split for case in cases)
                for split in ("development", "holdout", "edge")
            },
        },
        "execution": {
            "productSessions": len(products),
            "productSuccess": sum(row["status"] == "SUCCESS" for row in products),
            "productFailure": len(product_failures),
            "validLevelAssessment": (
                len(products) - len(product_failures) - len(missing_assessments)
            ),
            "missingLevelAssessment": len(missing_assessments),
            "primarySessions": len(primary),
            "primarySuccess": sum(row["status"] == "SUCCESS" for row in primary),
            "primaryValidLevelAssessment": sum(
                row["status"] == "SUCCESS" and row.get("levelAssessment") is not None
                for row in primary
            ),
            "referenceSuccess": len(references),
            "modelCalls": len(calls),
            "modelCallsScope": "session-level-assessment only",
            "referenceModelCalls": 0 if reused_reference else len(reference_rows),
            "reusedReferenceResults": len(reference_rows) if reused_reference else 0,
            "finishReasons": finish_reasons,
            "tokens": tokens,
            "tokensScope": "session-level-assessment only",
            "productCostUsd": decimal(product_cost),
            "referenceCostUsd": decimal(new_reference_cost),
            "historicalReferenceCostUsd": decimal(reference_cost) if reused_reference else "0.00",
            "totalCostUsd": decimal(product_cost + new_reference_cost),
            "latencyP50": statistics.median(
                row["latencySeconds"] for row in products
            ),
            "latencyP95": sorted(row["latencySeconds"] for row in products)[
                max(0, round(len(products) * 0.95) - 1)
            ],
        },
        "primary": {
            "comparable": len(comparable),
            "initialized": sum(
                item["row"]["bePolicy"]["changeType"] == "INITIALIZED"
                for item in comparable
            ),
            "withinRange": sum(item["distance"] == 0 for item in comparable),
            "withinOne": sum(
                item["distance"] is not None and item["distance"] <= 1
                for item in comparable
            ),
        },
        "holdout": {
            "comparable": len(holdout),
            "initialized": sum(
                item["row"]["bePolicy"]["changeType"] == "INITIALIZED"
                for item in holdout
            ),
            "withinRange": sum(item["distance"] == 0 for item in holdout),
            "withinOne": sum(
                item["distance"] is not None and item["distance"] <= 1
                for item in holdout
            ),
        },
        "repeatability": repeat_ranges,
        "domains": domain_stats,
        "failureReasons": failure_reasons,
        "directProductFallbacks": sum(
            row.get("bePolicy", {}).get("source") == "FALLBACK" for row in products
        ),
        "directProductNotApplied": sum(
            row.get("bePolicy", {}).get("changeType") == "NOT_APPLIED"
            for row in products
        ),
        "expectedBeFallbacks": len(product_failures) + len(missing_assessments),
        "expectedBeNotApplied": len(product_failures) + len(missing_assessments),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(args)
    cases = load_cases(args.cases)
    if args.reference_dir:
        if args.phase != "product":
            raise ValueError("--reference-dir is only supported for the product phase")
        reuse_reference(args, cases)
    if args.phase == "reference":
        run_reference(args, cases)
    elif args.phase == "product":
        run_product(args, cases)
    else:
        score(args, cases)


if __name__ == "__main__":
    main()
