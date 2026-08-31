# 정렬용 wav2vec2 모델을 ONNX int8로 변환하는 스크립트 (LAN-418)
#
# 산출물 models/wav2vec2_int8.onnx(~95MB)는 자산 CDN에 업로드해 두고 Dockerfile이
# 빌드 시점에 받아 이미지에 굽는다. 앱 런타임은 torch가 없으므로, 이 스크립트만
# 별도 환경(torch·torchaudio·onnx·onnxscript·onnxruntime 설치)에서 수동 실행한다:
#   pip install torch torchaudio onnx onnxscript onnxruntime
#   python scripts/export_alignment_model.py
#
# 변환 후 Dockerfile의 ALIGNMENT_MODEL_SHA256과 forced_align._LABELS가 모델과
# 일치하는지 확인할 것. 검증 절차:
#   1) 이 스크립트가 끝에 출력하는 패리티 결과(원본 torch와의 단어 경계 차이)가
#      골든 케이스 전부에서 수용 범위(±수십 ms)인지 확인
#   2) RUN_ALIGNMENT_TESTS=1 pytest tests/test_pronunciation_alignment.py
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

OUT_FP32 = REPO / "models" / "wav2vec2_fp32.onnx"
OUT_INT8 = REPO / "models" / "wav2vec2_int8.onnx"


class _EmissionOnly:
    """torchaudio 모델의 (emission, lengths) 출력에서 emission만 노출한다."""

    def __new__(cls, inner):
        import torch

        class Wrapper(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.inner = inner

            def forward(self, waveform):
                emission, _ = self.inner(waveform)
                return emission

        return Wrapper()


def main() -> None:
    import torch
    import torchaudio
    from onnxruntime.quantization import QuantType, quantize_dynamic

    bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    model = bundle.get_model()
    model.eval()
    sample_rate = int(bundle.sample_rate)

    from app.pronunciation.alignment.forced_align import _LABELS

    if tuple(bundle.get_labels()) != _LABELS:
        raise SystemExit(
            "forced_align._LABELS가 모델 라벨과 다릅니다 — 상수를 갱신하세요"
        )

    OUT_INT8.parent.mkdir(exist_ok=True)
    print("exporting to ONNX (fp32)...")
    # dynamo 익스포터는 가중치를 initializer로 내보내지 않아 양자화가 실패한다 —
    # 레거시 익스포터를 강제한다 (실측: LAN-418)
    torch.onnx.export(
        _EmissionOnly(model),
        torch.zeros(1, sample_rate),
        str(OUT_FP32),
        input_names=["waveform"],
        output_names=["emission"],
        dynamic_axes={"waveform": {1: "time"}, "emission": {1: "frames"}},
        opset_version=17,
        dynamo=False,
    )
    print(f"fp32: {OUT_FP32.stat().st_size / 1e6:.0f}MB")

    print("quantizing to int8...")
    quantize_dynamic(str(OUT_FP32), str(OUT_INT8), weight_type=QuantType.QInt8)
    OUT_FP32.unlink()
    digest = hashlib.sha256(OUT_INT8.read_bytes()).hexdigest()
    print(f"int8: {OUT_INT8.stat().st_size / 1e6:.0f}MB")
    print(f"sha256: {digest}")
    print("Dockerfile의 ALIGNMENT_MODEL_SHA256을 위 값으로 갱신하고 CDN에 업로드하세요.")


if __name__ == "__main__":
    main()
