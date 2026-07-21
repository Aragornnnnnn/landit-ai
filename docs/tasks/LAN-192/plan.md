# LAN-192 AI 로그 레벨 보존 구현 계획

**Goal:** AI 로그가 Python 로거의 실제 레벨을 CloudWatch 원문에 보존하도록 한다.

**Architecture:** 애플리케이션 시작 시 루트 로거를 공통 포맷으로 구성하고 Uvicorn 로거가 루트 핸들러를 사용하게 한다.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, `logging`, `unittest`.

### Task 1: 로그 포맷 회귀 테스트.

- [x] `WARNING`과 `ERROR` 레벨 출력 테스트를 먼저 작성한다.
- [x] 설정 모듈 부재로 RED를 확인한다.

### Task 2: 애플리케이션 로깅 구성.

- [x] `app/core/logging.py`에 공통 포맷과 초기화 함수를 추가한다.
- [x] 앱 생성 시 Sentry 초기화 전에 로깅을 구성한다.
- [x] Uvicorn 로거가 루트 핸들러로 전파되도록 한다.

### Task 3: 검증.

- [x] `.venv/bin/python -m unittest tests.test_logging -v`를 실행한다.
- [x] `.venv/bin/python -m unittest discover -s tests`를 실행한다.
- [ ] prod 배포 후 CloudWatch 원문과 Grafana 조회 결과를 확인한다.
