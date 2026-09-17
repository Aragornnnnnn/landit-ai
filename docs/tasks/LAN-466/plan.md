# LAN-466 AI 예외 전송 정책

## 기준과 범위

- 기준은 `develop`의 `f247bfe6`, 작업 브랜치는 `feat/LAN-466`이다. 2026-09-17 재확인 시 동일했다.
- BE 구현과 검증은 BE 저장소의 `docs/tasks/LAN-466/plan.md`에서 관리한다.
- LLM 평가 기준, 기억 후보 제외 조건, 재시도 횟수, 성공 응답 DTO는 변경하지 않는다.

## 경로별 전송 기준

| 경로 | 이전 | 적용 정책 |
| --- | --- | --- |
| 명시적 capture와 SDK 자동 수집 | 별도 정책, 요청 일부 필드만 제거 | 공통 before_send에서 결과 분류 및 허용 필드만 재구성 |
| OpenAI 자동 integration | 중간 provider 오류를 즉시 전송 | 자동 integration 비활성화 및 기존 패치의 OpenAI 이벤트 제외. 최종 기능 경계에서 보고 |
| 입력 검증·HTTP 오류 | 상태/클래스 위주 처리 | 내부 토큰으로 인증된 호출의 계약 위반은 failed, 외부 요청 거절은 expected_rejection. 405 Allow 유지 |
| 종료 문구·속마음·JSON 재생성 | 복구 후에도 전송하거나 복구 관측 누락 | 유효한 안전 응답·재생성 성공은 recovered 로그·메트릭. 설정·코드 결함이 원인이면 failed |
| 메시지 피드백 | HTTP 202 내부 FAILED 무전송 | 필수 결과 생성 실패는 failed |
| 수준 평가 | Core 재시도 실패 후 null 응답 | Core 유실은 failed, 재시도 성공·선택 Details 누락은 recovered |
| 기억 검수 | 근거 불일치를 하나의 이유로 기록 | refinement_fields_missing, source_id_mismatch, numbers_changed, source_message_missing_or_not_user, quote_not_in_source. 기존 후보 제외 동작 유지 |
| 나머지 생성·처리 오류 | 일부 server error 미전송 | 기존 최종 예외 경계에서 failed. 예외 타입/HTTP 상태만으로 제외하지 않음 |

`expected_rejection`, `recovered`, `failed`는 종료 결과다. BE의 `retrying`은 아직 결과가 확정되지 않은 중간 관측이다. 정상 대체 응답이 있어도 모델/API key/base URL 설정 문제, 코드 결함은 전송한다. provider 401/403/404 및 잘못된 URL은 설정·계약 결함으로 본다. 일시 연결 장애와 429의 안전한 종료 문구 대체는 recovered지만, 같은 장애로 피드백 등 필수 결과가 없으면 failed다.

내부 토큰이 비어 있는 기존 호환 모드는 유지한다. 이 모드에서는 신뢰된 BE 호출인지 증명할 수 없어 입력 검증 실패를 외부 요청으로 분류한다. 운영에서는 내부 인증 설정을 유지해야 한다.

## 관측·민감정보·중복

- 로그와 `landit.failure.outcomes` 메트릭은 workflow, failure_stage, reason, outcome, recovered를 사용한다. 시도 정보는 로그·이벤트의 attempt에 둔다.
- request_id는 서버 UUID다. 인증된 BE의 UUID만 이어 받는다. 메트릭에는 request_id를 넣지 않는다. 메트릭 exporter는 기존 관측 설정을 사용한다.
- Sentry 오류 이벤트에는 원인 타입·코드 위치와 안전한 태그만 남긴다. 예외 메시지, 요청 본문/헤더, user, context, extras, breadcrumb, 로컬 변수, 원문·토큰·음성을 제거한다. 예외 없는 결과 실패는 workflow/stage/reason으로 그룹을 나눈다.
- 동일 예외의 명시적·자동 수집을 한 번으로 제한한다. provider 중간 오류는 복구 결정을 기다리며, 최종 미처리 오류 자동 수집은 유지한다.
- 서비스 간 중복과 프로세스 내 중복은 구별한다. AI의 원인 실패와 BE의 필수 결과 유실은 각각 기록될 수 있으며 request_id로 연결한다. BE의 AI 오류 전체를 제외하지 않아 BE→AI 연결·타임아웃·저장 장애가 남는다.
- 이벤트 저장 정책과 Sentry 알림 라우팅은 별개다. 알림 설정은 변경하지 않았다.

## 검증

- 전체 `.venv/bin/python -m unittest discover -s tests`: 554개, 실패 0, 기존 환경 의존 skip 7개. 격리 worktree에서는 원본 저장소의 Python 3.12 venv 실행 파일을 사용했다.
- 새 관측 테스트 15개: 실제 메모리 transport의 이벤트/민감정보/중복, FastAPI 미처리·입력 오류, 405 Allow, HTTP 성공 내부 FAILED와 Core 유실, 기억 검수 이유, 복구 메트릭, 결과별 fingerprint, 운영 SDK integration 및 provider 설정 오류를 검증했다.
- 실제 provider 응답은 httpx.MockTransport로 대체했고 실제 Sentry/LLM 외부 전송은 하지 않았다. 기존 skip은 강제 정렬 모델/명시적 실행 옵션을 요구하는 테스트다.
- 독립 리뷰 지적을 반영한 집중 재리뷰와 마지막 원인 분류 경계 재검토에서 추가 확정 결함이 없었다.

독립 리뷰에서 OpenAI 자동 선행 전송, provider URL 결함 제외, 종료/속마음 복구 관측 누락을 확인하고 수정했다. 운영 초기화 설정을 사용하는 테스트를 별도로 추가했다.

배포 후에는 이벤트 수뿐 아니라 피드백 FAILED·평가 Core 유실·기억/표현 실패율, 복구 메트릭, 상태 저장 실패를 함께 대조해야 한다. 이 작업은 로컬 구현·검증이며 배포나 운영 효과를 입증하지 않는다.
