# 발음 분석용 오디오 디코드·변환 유틸리티 모듈
#
# ffmpeg subprocess로 m4a/mp3/wav/webm을 판정용 WAV로 변환한다.
# 원 샘플레이트를 유지한다 (PoC에서 16kHz 축소 시 오분류가 발생해 원본 유지).
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_AUDIO_DURATION_SECONDS = 30.0
_FFMPEG_TIMEOUT_SECONDS = 10.0
# duration 폴백 디코드 상한. 크롬 MediaRecorder의 webm은 스트리밍 컨테이너라
# duration 메타데이터가 없는 경우가 흔한데(ffprobe가 N/A 반환 — 실측 확인),
# opus는 압축률이 높아 크기 제한(10MB) 안에서도 수십 분짜리 오디오가 가능하다.
# 상한 없이 디코드해 길이를 재면 그 자체가 DoS 경로가 되므로 31초에서 끊는다.
_PROBE_DECODE_LIMIT_SECONDS = MAX_AUDIO_DURATION_SECONDS + 1.0
# 폴백 발생 빈도 관측용 프로세스 누적 카운트 (warning 로그에 실린다)
_duration_fallback_count = count(1)
# 이보다 적게 잘리면 침묵 컷을 적용하지 않는다. 컷의 목적은 폰 녹음의 비정상적으로 긴
# 가장자리 침묵(3초대) 제거다 — 1초 남짓의 자연스러운 리드인까지 자르면 판정 유형이
# 바뀌는 회귀가 실측됐다 (골든 s2_stress, 침묵 1.1초).
_MIN_TRIMMED_SILENCE_SECONDS = 2.0

# 앞뒤 침묵 제거: -35dB (="얼마나 조용해야 침묵으로 칠 거냐"의 기준) 이하가 0.3초 넘게 이어지는 가장자리 구간을 자른다.
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
    # 유저 음성 파생 바이트는 예외 로그·Sentry에 노출되면 안 되므로 repr에서 제외한다
    judgment_wav: bytes = field(repr=False)
    duration_seconds: float


def decode_user_audio(
    data: bytes, audio_format: str, deadline: float | None = None
) -> DecodedAudio:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise AudioDecodeError("ffmpeg is not available on this server")

    with tempfile.TemporaryDirectory(prefix="pronunciation-") as tmp_dir:
        source = Path(tmp_dir) / f"input.{audio_format}"
        source.write_bytes(data)

        duration = _measure_duration(source, Path(tmp_dir), deadline)
        if duration > MAX_AUDIO_DURATION_SECONDS:
            raise AudioDecodeError(
                f"audio is longer than {MAX_AUDIO_DURATION_SECONDS:.0f} seconds"
            )

        judgment = Path(tmp_dir) / "judgment.wav"
        trimmed = Path(tmp_dir) / "trimmed.wav"
        # 판정용은 앞뒤 침묵을 잘라 LLM이 듣는 길이를 줄인다 (지연이 오디오 길이에
        # 비례하고, 폰 녹음의 가장자리 잡음이 오탐을 만든다). 단, 실제로 잘린 침묵이
        # 1초 미만이면 원본을 쓴다 — 깨끗한 오디오에 컷을 적용하면 판정 유형이 바뀌는
        # 회귀가 실측됐다 (LAN-373 게이트 B: s2_stress STRESS→SOUND).
        _run_ffmpeg(
            [
                str(source),
                "-af",
                _EDGE_SILENCE_TRIM_FILTER,
                str(trimmed),
            ],
            deadline,
        )
        if duration - _probe_duration(trimmed, deadline) >= (
            _MIN_TRIMMED_SILENCE_SECONDS
        ):
            judgment = trimmed
        else:
            _run_ffmpeg([str(source), str(judgment)], deadline)
        return DecodedAudio(
            judgment_wav=judgment.read_bytes(),
            duration_seconds=duration,
        )


def convert_to_wav(
    data: bytes, source_format: str, deadline: float | None = None
) -> bytes:
    """참조 오디오(mp3 등)를 판정용 WAV로 변환한다."""
    with tempfile.TemporaryDirectory(prefix="pronunciation-ref-") as tmp_dir:
        source = Path(tmp_dir) / f"reference.{source_format}"
        target = Path(tmp_dir) / "reference.wav"
        source.write_bytes(data)
        _run_ffmpeg([str(source), str(target)], deadline)
        return target.read_bytes()


def _measure_duration(
    source: Path, tmp_dir: Path, deadline: float | None = None
) -> float:
    """오디오 실길이를 잰다. 컨테이너에 duration 메타데이터가 없으면 유계 디코드로 폴백.

    30초 검증은 어떤 경로로도 우회되지 않아야 한다(fail-closed): 폴백은 최대
    31초만 디코드하므로 아무리 긴 파일이 와도 CPU를 31초어치만 쓰고, 컷에 걸린
    출력은 30초 이상으로 측정돼 거부된다.
    """
    try:
        duration = _probe_duration(source, deadline)
    except AudioDecodeError:
        duration = 0.0
    if duration > 0:
        return duration
    logger.warning(
        "duration probe failed; measuring via bounded decode "
        "(format=%s, fallback_count=%d)",
        source.suffix.lstrip("."),
        next(_duration_fallback_count),
    )
    probe_wav = tmp_dir / "duration-probe.wav"
    _run_ffmpeg(
        [str(source), "-t", f"{_PROBE_DECODE_LIMIT_SECONDS:.0f}", str(probe_wav)],
        deadline,
    )
    measured = _probe_duration(probe_wav, deadline)
    if measured >= MAX_AUDIO_DURATION_SECONDS:
        raise AudioDecodeError(
            f"audio is longer than {MAX_AUDIO_DURATION_SECONDS:.0f} seconds"
        )
    return measured


def _probe_duration(source: Path, deadline: float | None = None) -> float:
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
        ],
        deadline,
    )
    try:
        return float(result.stdout.strip())
    except ValueError as error:
        raise AudioDecodeError("could not read audio duration") from error


def _run_ffmpeg(args: list[str], deadline: float | None = None) -> None:
    _run(["ffmpeg", "-v", "error", "-y", "-i", *args], deadline)


def _run(
    command: list[str], deadline: float | None = None
) -> subprocess.CompletedProcess:
    # 전체 분석 예산(deadline)이 있으면 subprocess 타임아웃을 남은 시간과 min으로 묶는다
    timeout = _FFMPEG_TIMEOUT_SECONDS
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AudioDecodeError("audio processing timed out")
        timeout = min(timeout, remaining)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise AudioDecodeError("audio processing timed out") from error
    if result.returncode != 0:
        raise AudioDecodeError(f"{command[0]} failed: {result.stderr.strip()[:200]}")
    return result
