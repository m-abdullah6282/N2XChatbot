import logging
import threading

import numpy as np
from huggingface_hub import hf_hub_download
from onnxruntime import InferenceSession, SessionOptions
from tokenizers import Tokenizer

logger = logging.getLogger(__name__)

MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
MAX_SEQ_LEN = 256
# Small batches keep peak RAM low on the 512MB Render instance.
BATCH_SIZE = 16

tokenizer: Tokenizer | None = None
session: InferenceSession | None = None
_input_names: set[str] = set()
_load_lock = threading.Lock()


def _load():
    """Load the ONNX model + fast tokenizer once (thread-safe). Uses the
    `tokenizers` library directly instead of `transformers`, which saves
    >150MB of RAM and a heavy import."""
    global tokenizer, session, _input_names
    if session is not None and tokenizer is not None:
        return
    with _load_lock:
        if session is not None and tokenizer is not None:
            return
        logger.info("Loading embedding model %s ...", MODEL_REPO)
        model_path = hf_hub_download(MODEL_REPO, filename="onnx/model.onnx")
        tokenizer_path = hf_hub_download(MODEL_REPO, filename="tokenizer.json")

        tok = Tokenizer.from_file(tokenizer_path)
        tok.enable_truncation(max_length=MAX_SEQ_LEN)
        tok.enable_padding(pad_id=0, pad_token="[PAD]")

        opts = SessionOptions()
        opts.intra_op_num_threads = 1
        sess = InferenceSession(
            model_path, sess_options=opts, providers=["CPUExecutionProvider"]
        )
        _input_names = {i.name for i in sess.get_inputs()}
        tokenizer, session = tok, sess
        logger.info("Embedding model ready (inputs: %s).", sorted(_input_names))


def preload():
    """Eagerly load the model (called from a startup background thread so the
    first chat request does not pay the download/initialisation cost)."""
    _load()


def _embed_batch(texts: list[str]) -> np.ndarray:
    encodings = tokenizer.encode_batch(texts)
    input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

    feed = {"input_ids": input_ids, "attention_mask": attention_mask}
    if "token_type_ids" in _input_names:
        feed["token_type_ids"] = np.zeros_like(input_ids)

    token_embeddings = session.run(None, feed)[0]  # (batch, seq, 384)

    # Mean pooling that IGNORES padding tokens (this is how all-MiniLM-L6-v2
    # is defined). Averaging over padded positions made a chunk's vector
    # depend on which other chunks shared its batch, so stored vectors and
    # single-text query vectors did not live in the same space.
    mask = attention_mask[..., None].astype(np.float32)
    summed = (token_embeddings * mask).sum(axis=1)
    counts = np.clip(mask.sum(axis=1), 1e-9, None)
    pooled = summed / counts

    norms = np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
    return pooled / norms


def _embed(texts: list[str]) -> list[list[float]]:
    _load()
    if not texts:
        return []
    results: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = [t if t and t.strip() else " " for t in texts[start : start + BATCH_SIZE]]
        results.extend(_embed_batch(batch).tolist())
    return results


def generate_embedding(text: str) -> list[float]:
    return _embed([text])[0]


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    return _embed(texts)
