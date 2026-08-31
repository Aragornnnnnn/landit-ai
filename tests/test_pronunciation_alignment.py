# wav2vec2(ONNX int8) 강제 정렬을 실제 모델로 검증하는 unittest 모듈
#
# 모델 파일(models/wav2vec2_int8.onnx, ~95MB)이 필요하므로 RUN_ALIGNMENT_TESTS=1
# 일 때만 실행한다 (파일이 없으면 그 안에서도 skip):
#   RUN_ALIGNMENT_TESTS=1 .venv/bin/python -m pytest tests/test_pronunciation_alignment.py
import os
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOLDEN_AUDIO = REPO / "docs" / "tasks" / "LAN-209" / "audio"
MODEL_PATH = REPO / "models" / "wav2vec2_int8.onnx"
SENTENCE_WORDS = [
    "There's",
    "nothing",
    "like",
    "hiking",
    "to",
    "clear",
    "my",
    "head",
]


@unittest.skipUnless(
    os.environ.get("RUN_ALIGNMENT_TESTS") == "1",
    "RUN_ALIGNMENT_TESTS=1 일 때만 실행",
)
@unittest.skipUnless(MODEL_PATH.is_file(), "models/wav2vec2_int8.onnx 필요")
class ForcedAlignmentTests(unittest.TestCase):
    def test_correct_wav_aligns_all_words_in_order(self):
        from app.pronunciation.alignment.forced_align import align_words

        wav = (GOLDEN_AUDIO / "correct_16k.wav").read_bytes()

        spans = align_words(wav, SENTENCE_WORDS)

        self.assertEqual([span.word for span in spans], SENTENCE_WORDS)
        for previous, current in zip(spans, spans[1:]):
            self.assertLess(previous.start_ms, current.start_ms)
            # 컷 규칙: 이전 단어 끝은 다음 단어 시작보다 앞서야 한다
            self.assertLessEqual(previous.end_ms, current.start_ms)
        self.assertGreaterEqual(spans[0].start_ms, 0)

    def test_alignment_fails_for_unalignable_word(self):
        from app.pronunciation.alignment.forced_align import (
            AlignmentError,
            align_words,
        )

        wav = (GOLDEN_AUDIO / "correct_16k.wav").read_bytes()

        with self.assertRaises(AlignmentError):
            align_words(wav, ["1234"])

    def test_alignment_fails_when_audio_is_too_short_for_sentence(self):
        # 문장 토큰 수보다 프레임이 부족하면 경로가 없다 — 예전 torch 구현과 동일 계약
        import io
        import wave

        from app.pronunciation.alignment.forced_align import (
            AlignmentError,
            align_words,
        )

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(16_000)
            f.writeframes(b"\x00\x00" * 1_600)  # 0.1초

        with self.assertRaises(AlignmentError):
            align_words(buffer.getvalue(), SENTENCE_WORDS)


class ViterbiUnitTests(unittest.TestCase):
    """모델 없이 Viterbi 정렬의 순수 로직을 검증한다 — 게이트 없이 항상 실행."""

    def align(self, log_probs, tokens):
        import numpy as np

        from app.pronunciation.alignment.forced_align import (
            _viterbi_forced_align,
        )

        return _viterbi_forced_align(np.array(log_probs, dtype=np.float32), tokens)

    def test_clear_emissions_align_to_expected_frames(self):
        # 프레임별로 토큰 2, blank, 토큰 3이 확실한 3프레임 → [2, 0, 3]
        high, low = 0.0, -10.0
        log_probs = [
            [low, low, high, low],
            [high, low, low, low],
            [low, low, low, high],
        ]

        self.assertEqual(self.align(log_probs, [2, 3]), [2, 0, 3])

    def test_repeated_token_requires_blank_between(self):
        # 같은 토큰 연속("LL")은 CTC 규칙상 사이에 blank가 강제된다
        high, low = 0.0, -10.0
        log_probs = [
            [low, low, high],
            [high, low, low],
            [low, low, high],
        ]

        self.assertEqual(self.align(log_probs, [2, 2]), [2, 0, 2])

    def test_too_few_frames_raise(self):
        from app.pronunciation.alignment.forced_align import AlignmentError

        log_probs = [[0.0, -1.0, -1.0]]

        with self.assertRaises(AlignmentError):
            self.align(log_probs, [2, 2])


class WarmUpTests(unittest.TestCase):
    """워밍업은 모델 없이 검증한다 (세션 로드는 mock) — 게이트 없이 항상 실행."""

    def test_warm_up_loads_session_and_runs_inference(self):
        from unittest.mock import MagicMock, patch

        from app.pronunciation.alignment import forced_align

        session = MagicMock()
        with patch.object(
            forced_align, "_load_session", return_value=session
        ):
            forced_align.warm_up()

        session.run.assert_called_once()

    def test_warm_up_failure_is_swallowed(self):
        from unittest.mock import patch

        from app.pronunciation.alignment import forced_align

        with (
            patch.object(
                forced_align, "_load_session", side_effect=RuntimeError("boom")
            ),
            self.assertLogs(forced_align.logger.name, level="ERROR"),
        ):
            forced_align.warm_up()  # 예외가 새어 나오면 테스트 실패


if __name__ == "__main__":
    unittest.main()
