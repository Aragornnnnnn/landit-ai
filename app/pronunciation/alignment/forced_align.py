# wav2vec2(ONNX int8) 강제 정렬로 단어별 타임스탬프를 산출하는 모듈
#
# LAN-209 타임스탬프 PoC 확정: WAV2VEC2_ASR_BASE_960H로 정답 문장을 오디오에 정렬해
# 단어별 start/end를 얻는다. 컷 보정 규칙까지 적용해 반환한다:
#   start-30ms ~ min(end+50ms, 다음 단어 start-10ms)
#
# LAN-418 경량화: 원본(torch fp32, 로드 피크 ~1GB)이 dev 메모리 한도를 넘어 OOM
# 재시작 루프를 만들어, 같은 모델을 ONNX int8(~95MB)로 양자화해 onnxruntime(CPU)으로
# 실행한다. 골든 12케이스 실측에서 원본 대비 단어 경계 차이 평균 0~30ms, 최악
# 121ms — 컷 패딩(30~50ms) 설계 여유 안이고 청취 검수도 통과했다. CTC Viterbi
# 정렬은 torch 의존을 없애기 위해 numpy로 직접 구현한다 (원본 torchaudio
# forced_align과의 패리티는 scripts/export_alignment_model.py 검증 절차로 확인).
import io
import logging
import re
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CUT_START_PADDING_MS = 30
CUT_END_PADDING_MS = 50
CUT_NEXT_WORD_GAP_MS = 10

# 모델 입력 규격. audio.py의 ffmpeg 변환이 이 샘플레이트의 mono WAV를 보장한다
ALIGNMENT_SAMPLE_RATE = 16_000
# WAV2VEC2_ASR_BASE_960H의 라벨 (torchaudio bundle.get_labels()와 동일 순서).
# ONNX로 떼어내면서 모델과 함께 여기 고정한다 — 모델 파일을 바꾸면 같이 바꿔야 한다
_LABELS = (
    "-", "|", "E", "T", "A", "O", "N", "I", "H", "S", "R", "D", "L", "U",
    "M", "W", "C", "F", "G", "Y", "P", "B", "V", "K", "'", "X", "J", "Q", "Z",
)
_BLANK = 0
_SEPARATOR = _LABELS.index("|")
_LABEL_INDEX = {label: index for index, label in enumerate(_LABELS)}
# 저장소 루트 기준 기본 모델 경로 (컨테이너에서는 /app/models/...)
_DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[3] / "models" / "wav2vec2_int8.onnx"
)

# 세션(~260MB)은 프로세스당 한 번만 로드해 캐시로 재사용한다. 락이 없으면 동시에
# 들어온 요청들이 각자 중복 로드하므로, 한 스레드만 로드하고 나머지는 완료까지 대기한다
_session_lock = threading.Lock()
_session_cache: dict[str, object] = {}
# 추론은 직렬로 묶는다: 동시 추론 1회당 활성화 메모리 ~170MB가 누적되고(실측),
# onnxruntime 메모리 아레나는 한 번 커지면 줄지 않아 겹친 피크가 상주로 굳는다.
# 추론(~0.3초)은 LLM 판정(수 초)과 병렬로 돌므로 대기 비용은 예산에 영향이 없다
_MAX_CONCURRENT_INFERENCES = 1
_inference_semaphore = threading.Semaphore(_MAX_CONCURRENT_INFERENCES)


class AlignmentError(Exception):
    """강제 정렬 실패."""


@dataclass(frozen=True)
class WordSpan:
    word: str
    start_ms: int
    end_ms: int


def align_words(
    alignment_wav: bytes, words: list[str], model_path: str | None = None
) -> list[WordSpan]:
    """16kHz mono PCM WAV에 단어 리스트를 정렬해 컷 보정된 ms span을 반환한다."""
    session = _load_session(model_path)
    tokens_per_word = [_tokenize(word) for word in words]

    waveform, wav_rate = _read_pcm_wav(alignment_wav)
    if wav_rate != ALIGNMENT_SAMPLE_RATE:
        # ffmpeg 변환(audio.py)이 보장하는 전제 — 어기면 데이터 경로 버그다
        raise AlignmentError(
            f"expected {ALIGNMENT_SAMPLE_RATE}Hz wav, got {wav_rate}Hz"
        )

    with _inference_semaphore:
        emission = session.run(None, {"waveform": waveform})[0][0]
    log_probs = _log_softmax(emission)

    flat_tokens: list[int] = []
    for index, word_tokens in enumerate(tokens_per_word):
        if index > 0:
            flat_tokens.append(_SEPARATOR)
        flat_tokens.extend(word_tokens)
    aligned_tokens = _viterbi_forced_align(log_probs, flat_tokens)

    token_spans = _merge_repeats(aligned_tokens)
    if len(token_spans) != len(flat_tokens):
        raise AlignmentError("aligned token count mismatch")

    frame_duration_ms = (
        waveform.shape[1] / log_probs.shape[0] / ALIGNMENT_SAMPLE_RATE * 1000.0
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


def _log_softmax(emission):
    import numpy as np

    shifted = emission - emission.max(axis=1, keepdims=True)
    return shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))


def _viterbi_forced_align(log_probs, tokens: list[int]) -> list[int]:
    """CTC Viterbi로 목표 토큰 시퀀스를 프레임에 강제 배치한다.

    표준 CTC 상태열(토큰 사이·양끝에 blank를 끼운 2L+1개)을 두고, 프레임마다
    유지/한 칸 전진/blank 건너뛰기(연속 동일 토큰이 아닐 때만) 중 최적 경로를
    고른다. 반환은 프레임별 토큰 id — torchaudio.functional.forced_align의
    aligned 출력과 같은 의미다.
    """
    import numpy as np

    num_frames = log_probs.shape[0]
    ext = np.empty(2 * len(tokens) + 1, dtype=np.int64)
    ext[0::2] = _BLANK
    ext[1::2] = tokens
    num_states = ext.size
    # blank 건너뛰기는 토큰 상태 중 직전 토큰과 다른 곳에서만 허용된다 (CTC 규칙)
    can_skip = np.zeros(num_states, dtype=bool)
    if num_states > 3:
        can_skip[3::2] = ext[3::2] != ext[1:-2:2]

    neg_inf = -np.inf
    scores = np.full(num_states, neg_inf)
    scores[0] = log_probs[0, ext[0]]
    if num_states > 1:
        scores[1] = log_probs[0, ext[1]]
    backptr = np.zeros((num_frames, num_states), dtype=np.int8)
    state_indexes = np.arange(num_states)
    for frame in range(1, num_frames):
        stay = scores
        step = np.concatenate(([neg_inf], scores[:-1]))
        skip = np.where(
            can_skip, np.concatenate(([neg_inf, neg_inf], scores[:-2])), neg_inf
        )
        stacked = np.stack([stay, step, skip])
        choice = stacked.argmax(axis=0)
        backptr[frame] = choice
        scores = stacked[choice, state_indexes] + log_probs[frame, ext]

    # 종료는 마지막 토큰 상태 또는 그 뒤 blank — 오디오가 토큰 수보다 짧으면 경로가 없다
    tail = scores[-2:] if num_states > 1 else scores[-1:]
    end_state = num_states - len(tail) + int(tail.argmax())
    if not np.isfinite(scores[end_state]):
        raise AlignmentError("audio is too short to align the sentence")

    state = end_state
    aligned = [0] * num_frames
    for frame in range(num_frames - 1, -1, -1):
        aligned[frame] = int(ext[state])
        state -= int(backptr[frame, state])
    return aligned


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


def _tokenize(word: str) -> list[int]:
    normalized = re.sub(r"[^A-Z']", "", word.upper())
    if not normalized:
        raise AlignmentError(f"word has no alignable characters: {word!r}")
    tokens = []
    for character in normalized:
        if character not in _LABEL_INDEX:
            raise AlignmentError(f"character not in model labels: {character!r}")
        tokens.append(_LABEL_INDEX[character])
    return tokens


def _read_pcm_wav(wav_bytes: bytes):
    """16-bit mono PCM WAV를 [1, T] float32 배열로 읽는다 (ffmpeg 산출물 전제)."""
    import numpy as np

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
        np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    )
    if channels > 1:
        waveform = waveform.reshape(-1, channels).mean(axis=1)
    return waveform.reshape(1, -1), sample_rate


def warm_up(model_path: str | None = None) -> None:
    """모델 로드와 첫 추론(커널 워밍)을 미리 치른다.

    int8 모델은 로드 0.2초·추론 0.3초 수준(로컬 실측)이라 필수는 아니지만,
    배포 직후 첫 요청이 초기화 비용을 떠안지 않게 유지한다. 워밍업 실패는
    로그만 남기고 서비스는 계속한다 (요청 경로의 지연 로드가 최후 수단).
    """
    import numpy as np

    try:
        session = _load_session(model_path)
        with_dummy = np.zeros((1, ALIGNMENT_SAMPLE_RATE), dtype=np.float32)
        # 1초짜리 무음으로 더미 추론 1회 — 첫 추론에만 붙는 초기화 비용을 미리 치른다
        with _inference_semaphore:
            session.run(None, {"waveform": with_dummy})
        logger.info("alignment model warm-up finished")
    except Exception:  # 워밍업 실패가 기동을 막으면 안 된다
        logger.exception("alignment model warm-up failed")


def _load_session(model_path: str | None = None):
    resolved = Path(model_path) if model_path else _DEFAULT_MODEL_PATH
    if not resolved.is_absolute():
        resolved = _DEFAULT_MODEL_PATH.parents[1] / resolved
    key = str(resolved)
    with _session_lock:
        if key not in _session_cache:
            import onnxruntime

            if not resolved.is_file():
                raise AlignmentError(f"alignment model file not found: {resolved}")
            _session_cache[key] = onnxruntime.InferenceSession(
                key, providers=["CPUExecutionProvider"]
            )
    return _session_cache[key]
