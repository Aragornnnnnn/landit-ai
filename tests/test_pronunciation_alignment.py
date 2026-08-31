# wav2vec2 강제 정렬을 실제 모델로 검증하는 unittest 모듈
#
# 모델 가중치(~378MB) 다운로드가 필요하므로 RUN_ALIGNMENT_TESTS=1 일 때만 실행한다:
#   RUN_ALIGNMENT_TESTS=1 .venv/bin/python -m pytest tests/test_pronunciation_alignment.py
import os
import unittest
from pathlib import Path

GOLDEN_AUDIO = (
    Path(__file__).resolve().parents[1] / "docs" / "tasks" / "LAN-209" / "audio"
)
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


class WarmUpTests(unittest.TestCase):
    """워밍업은 모델 없이 검증한다 (로드는 mock) — 게이트 없이 항상 실행."""

    def test_warm_up_loads_model_and_runs_inference(self):
        from unittest.mock import MagicMock, patch

        from app.pronunciation.alignment import forced_align

        model = MagicMock()
        with patch.object(
            forced_align, "_load_model", return_value=(model, ("|",), 16_000)
        ):
            forced_align.warm_up()

        model.assert_called_once()

    def test_warm_up_failure_is_swallowed(self):
        from unittest.mock import patch

        from app.pronunciation.alignment import forced_align

        with (
            patch.object(
                forced_align, "_load_model", side_effect=RuntimeError("boom")
            ),
            self.assertLogs(forced_align.logger.name, level="ERROR"),
        ):
            forced_align.warm_up()  # 예외가 새어 나오면 테스트 실패


if __name__ == "__main__":
    unittest.main()
