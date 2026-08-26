# LAN-373 발음 평가 AI 서버 구현 계획

요구사항 전문은 [issue.md](./issue.md), PoC 근거는 [LAN-209 plan.md](../LAN-209/plan.md)와
`scripts/poc_pronunciation_v2.py` 참고. 이 문서가 구현의 단일 기준 문서다.

## 확정 결정

- 오디오 전달: JSON + base64 (`userAudio` + `userAudioFormat`), 참조 음성은 URL로 받아 서버가 다운로드
- 경로: `POST /api/v1/pronunciation/analyze` (기존 prefix 컨벤션 유지)
- 요청에 `accentLocale`(EN_US|EN_GB|EN_AU) 포함 — 억양 힌트 실험·억양별 리포트 분리용
- TTS: OpenRouter 경유, locale별 3벌
  - EN_US: `microsoft/mai-voice-2` / `en-US-Harper:MAI-Voice-2`
  - EN_AU: `deepgram/aura-2` / `aura-2-hyperion-en`
  - EN_GB: `deepgram/aura-2` / `aura-2-draco-en`
- **작업 3(TTS 생성)은 `landit-iac` 저장소에서 진행한다.** 콘텐츠 사전 생성은 앱 런타임이
  아니라 운영 작업이고, 같은 성격의 `scripts/scenario_question_audio.py`(LAN-351)가 이미
  거기 있다. 이 이슈는 두 저장소에 걸친다: **작업 1·2·4는 `landit-ai`, 작업 3은 `landit-iac`**.
- S3 키: `content/expression-pronunciation-audio/{expressionId}/{locale}/{종류}/{fingerprint}.mp3`
- 파일명은 **생성 계약의 sha256 핑거프린트**를 쓴다 (`{model, providerVoiceId, text,
  responseFormat}`). 예측 가능한 이름(`sentence.mp3`)을 쓰자던 초기 방침은 철회했다 —
  핑거프린트라야 재생성 시 키가 바뀌어 CDN 캐시가 자연히 무효화되고, 그래야
  `immutable` 캐시 정책을 안전하게 걸 수 있다. URL 갱신 정보는 매니페스트로 BE에 넘긴다.
- S3 버킷: `landit-content-982529430654`
- S3 크리덴셜: **AWS CLI 기본 자격증명**에 위임한다. 정적 IAM 키를 발급하자던 초기 방침은
  철회했다 — 기존 파이프라인이 `aws s3api`를 subprocess로 호출하며 CLI 설정을 그대로 쓴다.
- S3 업로드: 계획(dry-run)이 기본, `--execute`로 실제 업로드
- `userAudio` base64는 요청 로그·에러 로그·Sentry에 절대 노출 금지 (테스트로 고정)
- 서버측 타임아웃: Gemini 호출 15초, 참조 다운로드 5초 (BE 타임아웃 20초보다 먼저 에러 반환)

## 작업 0 — 선행 스파이크: 억양별 판정 검증

본 구현의 억양·확장 필드 스펙 확정 전에 결과를 보고한다. 작업 1은 병렬 진행 가능.

1. OpenRouter TTS 호출 검증 겸 GB/AU 참조 음성 생성 (aura-2 draco/hyperion, 골든 셋 문장 4개
   + mai-voice-2 1건) — 작업 3의 최대 리스크(호출 형태 미검증)를 같이 해소
2. 영국식/호주식 의사-화자 발화 샘플 준비 (타사 TTS 합성; 정상 발화 + 미국식 발음 유도 케이스)
3. 미니 골든 셋 실행 (`poc_pronunciation_v2.py` 재사용):
   - GB/AU 참조 + 해당 억양 정상 발화 → 오탐 0 확인
   - GB 참조 + 미국식 발화(water, schedule 류) → 오류 검출 확인
   - 확장 필드(userDisplay/span/stressIndex) 품질 확인 (확장 프롬프트로 실행)
4. 결과 보고 후 판단: 품질 OK → 본 구현 / NG → 출시 범위 결정을 팀에 회부

## 작업 1 — 분석 API

새 파일: `app/models/pronunciation.py`, `app/pronunciation/audio.py`(ffmpeg 디코드 — Gemini용
원 샘플레이트 WAV + 정렬용 16kHz mono, ≤30초 검증, 실패 시 400 `INVALID_AUDIO`),
`app/pronunciation/llm/compare.py`(PoC compare 설정 그대로: temperature 0, max_tokens 4000,
`reasoning effort low`, 기준 텍스트 앵커링 금지, 파싱 실패 1회 재시도 후 502),
`app/pronunciation/alignment/forced_align.py`(torchaudio `WAV2VEC2_ASR_BASE_960H` +
`forced_align`, lazy singleton, 컷 보정 `start−30ms ~ min(end+50ms, 다음 단어 start−10ms)`),
`app/pronunciation/application/analysis_service.py`(디코드 → [참조 다운로드→Gemini] ∥ [정렬]
병렬 → order 병합, `SOUND→PHONEME_ERROR`/`STRESS→STRESS_ERROR`),
`app/api/pronunciation.py`.

수정: `app/main.py`(라우터 등록), `app/core/config.py`(`pronunciation_model` 등),
`app/common/errors.py`(`INVALID_AUDIO`), `pyproject.toml`(torch/torchaudio CPU·httpx·boto3),
`Dockerfile`(ffmpeg, torch CPU 인덱스, wav2vec2 가중치 프리다운로드).

## 작업 2 — Gemini 출력 확장 + 골든 셋 회귀 (스파이크 결과 반영 후 확정)

- COMPARE_PROMPT 확장: `userHeard`(respelling), `targetSpan`/`userSpan`, `stressIndex` 추가
- `scripts/eval_pronunciation_golden.py`: 골든 셋 24케이스 × 2회, 정확일치/오탐/p50/확장 필드
  테이블/억양별 성적. 결과 JSON과 리포트를 `docs/tasks/LAN-373/`에 보존
- 억양별 케이스는 스파이크 산출물을 회귀 셋에 편입. 미검증 억양이 남으면 리포트에 명시
- 폴백: 성능 저하 또는 p50>5초 시 확장 필드 제거 스펙으로 보고 (프롬프트 기본/확장 2벌 유지)

## 작업 3 — TTS 사전 생성 파이프라인

`scripts/generate_pronunciation_tts.py`: 표현 JSON 입력 → locale별 3종
(`expression.mp3`, `sentence.mp3`, `words/{order}-{word}.mp3`, 단어는 단독 생성) →
로컬 `out/` + BE 저장용 매니페스트 JSON. `--upload` 시 boto3 업로드, 기본 dry-run.
locale→(model, voice) 매핑은 확정값 기본 + JSON 설정 오버라이드.

### 기존 파이프라인 조사 결과 (2026-08-26)

**이 저장소에는 TTS 생성·S3 업로드 코드가 없다.** 현재도 없고 이력에도 없다
(`git log -S"boto3"`, `-S"scenario-question-audio"` 모두 결과 없음). 프로덕션 버킷의
`content/scenario-question-audio/{questionId}/{해시}.mp3`를 만드는 파이프라인은
BE(Spring) 저장소에 있는 것으로 보인다.

따라서 작업 3은 이 저장소에 새 스크립트로 만든다. 다만 다음 두 가지는 BE 파이프라인을
확인한 뒤 맞춘다.

- **파일명 해시 규칙**: 캐시 무효화 목적으로 추정되나 규칙을 모른 채 유사하게 만들면
  BE 기대와 어긋나므로 추측하지 않는다. BE 코드 확인 후 동일 규칙을 적용한다.
- **TTS 프로바이더**: BE가 이미 쓰는 프로바이더가 있다면 통일을 검토한다.
  단 OpenRouter 경유 호출은 이번 스파이크에서 3 locale 모두 검증 완료라
  (`spike-accent.md` 1절) 이 저장소 단독으로도 진행 가능하다.

## 작업 4 — 발음 기준 데이터 생성

`scripts/generate_pronunciation_reference.py` (`--locale` 필수, AI 호출 없음):
EN_US는 cmudict, EN_GB는 사전 소스 조사·적용(britfone/espeak-ng/Wiktionary 후보),
EN_AU는 EN_GB 재사용 여부 제안. 소스 미확정 시 "EN_US 생성 + GB/AU 조사 리포트"로 분리.
음절화(모음 기준 onset 최대화) + phoneme→respelling 매핑으로 `nativeDisplay`/`syllables`/
`stressIndex`(무강세 기능어 −1) 생성. BE `words_payload` 형식 JSON + 검수용 CSV, OOV 목록 출력.

## 테스트·검증

- `tests/test_pronunciation_api.py`(FakeCompletions + 정렬 patch, userAudio 로그 미노출 테스트),
  `tests/test_pronunciation_merge.py`(순수 함수), `tests/test_pronunciation_alignment.py`
  (`RUN_ALIGNMENT_TESTS=1` 게이트, `fa_cut_*` 산출물과 근사 비교)
- 완료 기준: ruff+pytest 통과 · 정렬 실측 · 골든 셋 24/24·오탐 0·p50≤5초 실측 리포트 ·
  analyze E2E 1회 · TTS dry-run 3 locale + (크리덴셜 주입 후) 실제 S3 업로드 · 기준 데이터 샘플 출력

## 진행 기록

- [x] 작업 0 스파이크 결과 보고 → [spike-accent.md](./spike-accent.md)
- [x] 작업 1 분석 API — E2E 실측(사람 녹음, 로컬 서버): 정상 발화 3/3 오탐 0·지연 중앙값
  4.4초, 오류 케이스는 묘사 호출이 더해져 ~7.7초(BE 타임아웃 내). 판정용 오디오
  가장자리 침묵 컷(-35dB)이 지연·오탐·문장 끝 억양 검출을 동시에 개선했다
- [x] 작업 2 골든 셋 회귀 — 검증본 5회: 59/60, 오탐 run 1.7%, p50 4.0초.
  판정은 회차 간 변동이 있어 2회 측정으로는 오탐률 판정 불가(5회 이상 필요).
  오탐 허용 기준(1.7%)은 기획 결정 대기
- [x] 작업 3 TTS 파이프라인 — landit-iac `feat/LAN-377` (LAN-377로 분리).
  verify-accent·S3 재사용 포함, 실제 업로드는 AWS 크리덴셜 대기
- [x] 작업 4 기준 데이터 스크립트 — EN_US 생성 완료(사람 기준과 7/8 일치, 강세 8/8).
  EN_GB/AU는 발음 사전 미확보로 미생성 — 소스(britfone/espeak-ng) 조사 필요
- [ ] 실제 S3 업로드 1건 검증 (`upload --execute`)
- [ ] EN_GB/AU 발음 사전 확보 → 기준 데이터·accentContrast 생성
- [ ] EN_AU 억양 판정은 사람 검증 없음 (TTS 의사-화자 대조만 정확) — 출시 범위 결정 필요
