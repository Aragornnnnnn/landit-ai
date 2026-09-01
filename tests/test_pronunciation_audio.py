# 오디오 디코드·duration 검증을 실제 ffmpeg로 확인하는 unittest 모듈
#
# 크롬 MediaRecorder의 webm은 스트리밍 컨테이너라 duration 메타데이터가 없다.
# ffmpeg 파이프 출력(-f webm pipe:1)은 seek이 불가해 같은 상태를 재현하므로,
# 이 픽스처로 유계 디코드 폴백 경로를 검증한다. ffmpeg가 없는 환경은 skip한다.
import io
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

_FFMPEG_AVAILABLE = (
    shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
)


def _make_sine_wav(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            str(path),
        ],
        check=True,
    )


def _encode(source: Path, target: Path) -> bytes:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(source), str(target)],
        check=True,
    )
    return target.read_bytes()


def _encode_streaming_webm(source: Path) -> bytes:
    # 파이프 출력은 seek이 불가해 컨테이너에 Duration 요소가 기록되지 않는다
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(source),
            "-c:a",
            "libopus",
            "-f",
            "webm",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return result.stdout


def _probe_format_duration(data: bytes, suffix: str, tmp_dir: Path) -> str:
    target = tmp_dir / f"probe-fixture.{suffix}"
    target.write_bytes(data)
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@unittest.skipUnless(_FFMPEG_AVAILABLE, "ffmpeg/ffprobe가 설치된 환경에서만 실행")
class DecodeUserAudioTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pronunciation-audio-test-")
        self.tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _streaming_webm(self, seconds: float) -> bytes:
        source = self.tmp_dir / "source.wav"
        _make_sine_wav(source, seconds)
        data = _encode_streaming_webm(source)
        # 픽스처 유효성: duration 메타데이터가 없어야 폴백 경로를 실제로 지난다.
        # ffmpeg 버전 변화로 파이프 출력에 duration이 생기면 여기서 실패해 알려준다.
        self.assertEqual(
            _probe_format_duration(data, "webm", self.tmp_dir), "N/A"
        )
        return data

    def test_streaming_webm_without_duration_metadata_decodes(self):
        from app.pronunciation.audio import ALIGNMENT_SAMPLE_RATE, decode_user_audio

        decoded = decode_user_audio(self._streaming_webm(5.0), "webm")

        self.assertAlmostEqual(decoded.duration_seconds, 5.0, delta=0.2)
        self.assertGreater(len(decoded.judgment_wav), 0)
        with wave.open(io.BytesIO(decoded.alignment_wav)) as alignment:
            self.assertEqual(alignment.getframerate(), ALIGNMENT_SAMPLE_RATE)
            self.assertEqual(alignment.getnchannels(), 1)

    def test_streaming_webm_longer_than_limit_is_rejected(self):
        from app.pronunciation.audio import AudioDecodeError, decode_user_audio

        # 유계 디코드(31초 컷)에 걸려 30초 이상으로 측정되고 거부돼야 한다
        with self.assertRaises(AudioDecodeError) as ctx:
            decode_user_audio(self._streaming_webm(32.0), "webm")
        self.assertIn("longer than", str(ctx.exception))

    def test_existing_formats_still_decode(self):
        from app.pronunciation.audio import decode_user_audio

        source = self.tmp_dir / "source.wav"
        _make_sine_wav(source, 4.0)
        for suffix in ("wav", "mp3", "m4a"):
            with self.subTest(format=suffix):
                data = _encode(source, self.tmp_dir / f"regression.{suffix}")
                decoded = decode_user_audio(data, suffix)
                self.assertAlmostEqual(decoded.duration_seconds, 4.0, delta=0.2)

    def test_garbage_bytes_are_rejected(self):
        from app.pronunciation.audio import AudioDecodeError, decode_user_audio

        with self.assertRaises(AudioDecodeError):
            decode_user_audio(b"not audio at all", "webm")


class FfmpegConcurrencyCapTests(unittest.TestCase):
    """ffmpeg subprocess는 동시 실행이 상한(4)으로 묶인다 — ffmpeg 없이 항상 실행.

    상한이 없으면 동시 요청 수만큼 프로세스가 떠서 메모리 한도를 뚫는다
    (1024m 한도 부하 실험에서 동시 30요청 OOM 실측 — LAN-418 후속).
    """

    def test_concurrent_runs_are_capped(self):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from subprocess import CompletedProcess
        from unittest.mock import patch

        from app.pronunciation import audio

        state = {"active": 0, "max_active": 0}
        state_lock = threading.Lock()

        def fake_run(command, **kwargs):
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            time.sleep(0.05)
            with state_lock:
                state["active"] -= 1
            return CompletedProcess(command, 0, stdout="", stderr="")

        with (
            patch.object(audio.subprocess, "run", side_effect=fake_run),
            ThreadPoolExecutor(max_workers=12) as executor,
        ):
            futures = [
                executor.submit(audio._run, ["ffmpeg", "-version"])
                for _ in range(12)
            ]
            for future in futures:
                future.result()

        self.assertLessEqual(state["max_active"], audio._MAX_CONCURRENT_FFMPEG)
        # 상한까지는 실제로 병렬로 돈다 (전부 직렬이면 상한 설정이 무의미)
        self.assertGreater(state["max_active"], 1)


if __name__ == "__main__":
    unittest.main()
