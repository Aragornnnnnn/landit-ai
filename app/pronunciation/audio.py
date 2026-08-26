# 발음 분석용 오디오 디코드·변환 유틸리티 모듈
#
# ffmpeg subprocess로 m4a/mp3/wav를 두 가지 WAV로 변환한다:
#   - 판정용: 원 샘플레이트 유지 (PoC에서 16kHz 축소 시 오분류가 발생해 원본 유지)
#   - 정렬용: wav2vec2 입력 규격인 16kHz mono
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_AUDIO_DURATION_SECONDS = 30.0
ALIGNMENT_SAMPLE_RATE = 16_000
_FFMPEG_TIMEOUT_SECONDS = 10.0

# 앞뒤 침묵 제거: -35dB 이하가 0.3초 넘게 이어지는 가장자리 구간을 자른다.
# 발화 사이 침묵은 건드리지 않는다 (뒤집어서 앞만 자르는 방식을 양방향 적용).
_EDGE_SILENCE_TRIM_FILTER = (
    "silenceremove=start_periods=1:start_threshold=-35dB:start_silence=0.3,"
    "areverse,"
    "silenceremove=start_periods=1:start_threshold=-35dB:start_silence=0.3,"
    "areverse"
)


class AudioDecodeError(Exception):
    """오디오 디코드·검증 실패. 원본 데이터는 메시지에 포함하지 않는다."""


@dataclass(frozen=True)
class DecodedAudio:
    judgment_wav: bytes
    alignment_wav: bytes
    duration_seconds: float


def decode_user_audio(data: bytes, audio_format: str) -> DecodedAudio:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise AudioDecodeError("ffmpeg is not available on this server")

    with tempfile.TemporaryDirectory(prefix="pronunciation-") as tmp_dir:
        source = Path(tmp_dir) / f"input.{audio_format}"
        source.write_bytes(data)

        duration = _probe_duration(source)
        if duration > MAX_AUDIO_DURATION_SECONDS:
            raise AudioDecodeError(
                f"audio is longer than {MAX_AUDIO_DURATION_SECONDS:.0f} seconds"
            )

        judgment = Path(tmp_dir) / "judgment.wav"
        alignment = Path(tmp_dir) / "alignment.wav"
        # 판정용은 앞뒤 침묵을 잘라 LLM이 듣는 길이를 줄인다 (지연이 오디오 길이에
        # 비례한다). 정렬용은 타임스탬프가 앱의 원본 녹음 재생 구간이므로 원본 그대로 둔다.
        _run_ffmpeg(
            [
                str(source),
                "-af",
                _EDGE_SILENCE_TRIM_FILTER,
                str(judgment),
            ]
        )
        _run_ffmpeg(
            [
                str(source),
                "-ar",
                str(ALIGNMENT_SAMPLE_RATE),
                "-ac",
                "1",
                str(alignment),
            ]
        )
        return DecodedAudio(
            judgment_wav=judgment.read_bytes(),
            alignment_wav=alignment.read_bytes(),
            duration_seconds=duration,
        )


def convert_to_wav(data: bytes, source_format: str) -> bytes:
    """참조 오디오(mp3 등)를 판정용 WAV로 변환한다."""
    with tempfile.TemporaryDirectory(prefix="pronunciation-ref-") as tmp_dir:
        source = Path(tmp_dir) / f"reference.{source_format}"
        target = Path(tmp_dir) / "reference.wav"
        source.write_bytes(data)
        _run_ffmpeg([str(source), str(target)])
        return target.read_bytes()


def _probe_duration(source: Path) -> float:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ]
    )
    try:
        return float(result.stdout.strip())
    except ValueError as error:
        raise AudioDecodeError("could not read audio duration") from error


def _run_ffmpeg(args: list[str]) -> None:
    _run(["ffmpeg", "-v", "error", "-y", "-i", *args])


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise AudioDecodeError("audio processing timed out") from error
    if result.returncode != 0:
        raise AudioDecodeError(f"{command[0]} failed: {result.stderr.strip()[:200]}")
    return result
