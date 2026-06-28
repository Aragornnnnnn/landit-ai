# landit-ai

Python 3.12, FastAPI 기반 AI 서버입니다.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python3.12 -m pip install -e .
```

## Test

```bash
python3.12 -m unittest discover -s tests
```

## Run

```bash
uvicorn app.main:app --reload
```

환경변수 예시는 `.env.example`을 기준으로 설정합니다.
