# wav2vec2 강제 정렬로 단어별 타임스탬프를 산출하는 모듈
#
# LAN-209 타임스탬프 PoC 확정: torchaudio WAV2VEC2_ASR_BASE_960H(CPU)로 정답 문장을
# 오디오에 정렬해 단어별 start/end를 얻는다. 컷 보정 규칙까지 적용해 반환한다:
#   start-30ms ~ min(end+50ms, 다음 단어 start-10ms)
import io
import logging
import re
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CUT_START_PADDING_MS = 30
CUT_END_PADDING_MS = 50
CUT_NEXT_WORD_GAP_MS = 10

_model_lock = threading.Lock()
_bundle_cache: dict[str, object] = {}


class AlignmentError(Exception):
    """강제 정렬 실패."""


@dataclass(frozen=True)
class WordSpan:
    word: str
    start_ms: int
    end_ms: int


def align_words(alignment_wav: bytes, words: list[str]) -> list[WordSpan]:
    """16kHz mono PCM WAV에 단어 리스트를 정렬해 컷 보정된 ms span을 반환한다."""
    import torch
    import torchaudio

    model, labels, sample_rate = _load_model()
    tokens_per_word = [_tokenize(word, labels) for word in words]

    waveform, wav_rate = _read_pcm_wav(alignment_wav)
    if wav_rate != sample_rate:
        waveform = torchaudio.functional.resample(waveform, wav_rate, sample_rate)

    with torch.inference_mode():
        emission, _ = model(waveform)
        emission = torch.log_softmax(emission, dim=-1)

    separator = labels.index("|")
    flat_tokens: list[int] = []
    for index, word_tokens in enumerate(tokens_per_word):
        if index > 0:
            flat_tokens.append(separator)
        flat_tokens.extend(word_tokens)
    targets = torch.tensor([flat_tokens], dtype=torch.int32)
    try:
        aligned_tokens, _scores = torchaudio.functional.forced_align(
            emission, targets, blank=0
        )
    except Exception as error:  # noqa: BLE001 — torch 내부 예외를 정렬 실패로 통일
        raise AlignmentError(str(error)) from error

    token_spans = _merge_repeats(aligned_tokens[0].tolist())
    if len(token_spans) != len(flat_tokens):
        raise AlignmentError("aligned token count mismatch")

    frame_duration_ms = (
        waveform.size(1) / emission.size(1) / sample_rate * 1000.0
    )
    raw_spans: list[tuple[float, float]] = []
    cursor = 0
    for index, word_tokens in enumerate(tokens_per_word):
        if index > 0:
            cursor += 1  # 단어 사이 '|' 구분 토큰 건너뛰기
        first = token_spans[cursor]
        last = token_spans[cursor + len(word_tokens) - 1]
        raw_spans.append(
            (first[0] * frame_duration_ms, (last[1] + 1) * frame_duration_ms)
        )
        cursor += len(word_tokens)

    return _apply_cut_rule(words, raw_spans)


def _apply_cut_rule(
    words: list[str], raw_spans: list[tuple[float, float]]
) -> list[WordSpan]:
    spans: list[WordSpan] = []
    for index, (word, (start, end)) in enumerate(zip(words, raw_spans)):
        cut_start = max(0.0, start - CUT_START_PADDING_MS)
        cut_end = end + CUT_END_PADDING_MS
        if index + 1 < len(raw_spans):
            next_start = raw_spans[index + 1][0]
            cut_end = min(cut_end, next_start - CUT_NEXT_WORD_GAP_MS)
        cut_end = max(cut_end, cut_start)
        spans.append(
            WordSpan(word=word, start_ms=round(cut_start), end_ms=round(cut_end))
        )
    return spans


def _merge_repeats(aligned: list[int]) -> list[tuple[int, int]]:
    """blank(0)을 제외하고 연속 프레임을 (시작, 끝) 프레임 span으로 병합한다."""
    spans: list[tuple[int, int]] = []
    previous_token = 0
    for frame, token in enumerate(aligned):
        if token == 0:
            previous_token = 0
            continue
        if token == previous_token:
            spans[-1] = (spans[-1][0], frame)
        else:
            spans.append((frame, frame))
        previous_token = token
    return spans


def _tokenize(word: str, labels: tuple[str, ...]) -> list[int]:
    label_index = {label: index for index, label in enumerate(labels)}
    normalized = re.sub(r"[^A-Z']", "", word.upper())
    if not normalized:
        raise AlignmentError(f"word has no alignable characters: {word!r}")
    tokens = []
    for character in normalized:
        if character not in label_index:
            raise AlignmentError(f"character not in model labels: {character!r}")
        tokens.append(label_index[character])
    return tokens


def _read_pcm_wav(wav_bytes: bytes):
    """16-bit mono PCM WAV를 [1, T] float 텐서로 읽는다 (ffmpeg 산출물 전제)."""
    import wave

    import torch

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
    except wave.Error as error:
        raise AlignmentError(f"invalid wav payload: {error}") from error
    if sample_width != 2:
        raise AlignmentError(f"expected 16-bit PCM wav, got {sample_width * 8}-bit")

    waveform = (
        torch.frombuffer(bytearray(frames), dtype=torch.int16).to(torch.float32)
        / 32768.0
    )
    if channels > 1:
        waveform = waveform.view(-1, channels).mean(dim=1)
    return waveform.unsqueeze(0), sample_rate


def warm_up() -> None:
    """모델 로드와 첫 추론(커널 워밍)을 미리 치른다.

    모델(~378MB) 로드를 첫 사용자 요청 안에서 치르면 17초 분석 예산을 넘겨
    배포 직후 연쇄 503이 난다 — 후속 요청도 _model_lock에 매달려 같이 죽는
    것을 dev에서 실측했다. 워밍업 실패는 로그만 남기고 서비스는 계속한다
    (요청 경로의 지연 로드가 최후 수단으로 남아 있다).
    """
    import torch

    try:
        model, _labels, sample_rate = _load_model()
        with torch.inference_mode():
            model(torch.zeros(1, sample_rate))
        logger.info("alignment model warm-up finished")
    except Exception:  # 워밍업 실패가 기동을 막으면 안 된다
        logger.exception("alignment model warm-up failed")


def _load_model():
    with _model_lock:
        if "model" not in _bundle_cache:
            import torchaudio

            bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
            model = bundle.get_model()
            model.eval()
            _bundle_cache["model"] = model
            _bundle_cache["labels"] = bundle.get_labels()
            _bundle_cache["sample_rate"] = int(bundle.sample_rate)
    return (
        _bundle_cache["model"],
        _bundle_cache["labels"],
        _bundle_cache["sample_rate"],
    )
