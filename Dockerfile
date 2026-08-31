# Landit AI 앱 이미지를 빌드하는 최소 Dockerfile
FROM python:3.12-slim

ARG APP_VERSION=local

ENV APP_VERSION=${APP_VERSION} \
    TZ=Asia/Seoul \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app

RUN apt-get update \
    && apt-get install --no-install-recommends -y tzdata ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# torch/torchaudio는 CPU 전용 휠로 설치해 이미지 크기를 줄인다
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch torchaudio \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir .

# wav2vec2 정렬 모델(~378MB)을 빌드 시점에 내려받아 이미지에 포함한다 (런타임 다운로드 금지)
RUN python -c "import torchaudio; torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.get_model()"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
