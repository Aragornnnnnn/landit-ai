# Landit AI 앱 이미지를 빌드하는 최소 Dockerfile
FROM python:3.12-slim

ARG APP_VERSION=local
# 정렬용 wav2vec2 int8 ONNX 모델(~95MB). 원본과 달리 우리가 양자화해 만든 파일이라
# 자산 CDN에 직접 호스팅한다 (재생성 절차: scripts/export_alignment_model.py).
# CDN 버킷 정책이 content/* 프리픽스만 공개하므로 경로가 content/ 아래여야 한다
ARG ALIGNMENT_MODEL_URL=https://d19azau1un4t7r.cloudfront.net/content/models/wav2vec2_int8.onnx
ARG ALIGNMENT_MODEL_SHA256=a0e9cd656e3c6cd2fcaadf93a4fae10e6449096c53ccda9f67797f2578dd63ee

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

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# 정렬 모델을 빌드 시점에 내려받아 이미지에 포함한다 (런타임 다운로드 금지).
# 체크섬 불일치는 빌드 실패로 fail-closed — 모델 교체 시 SHA와 라벨 상수를 함께 갱신한다
RUN python - <<'EOF'
import hashlib
import os
import urllib.request

url = os.environ.get("ALIGNMENT_MODEL_URL")
expected = os.environ.get("ALIGNMENT_MODEL_SHA256")
os.makedirs("/app/models", exist_ok=True)
target = "/app/models/wav2vec2_int8.onnx"
urllib.request.urlretrieve(url, target)
digest = hashlib.sha256(open(target, "rb").read()).hexdigest()
assert digest == expected, f"alignment model checksum mismatch: {digest}"
print(f"alignment model ready ({os.path.getsize(target)/1e6:.0f}MB)")
EOF

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
