"""GigaAM v3 inference runtime on Apple MLX (Metal).

Self-contained port of the Conformer encoder and the CTC / RNN-T heads of
SaluteDevices' GigaAM v3 (https://github.com/salute-developers/GigaAM, MIT),
loading the MLX checkpoints published by ``al-bo`` on HuggingFace:

    al-bo/gigaam-v3-e2e-rnnt-mlx   (punctuation + casing, SentencePiece, recommended)
    al-bo/gigaam-v3-rnnt-mlx       (lowercase, char-wise, no punctuation)
    al-bo/gigaam-v3-ctc-mlx

Checkpoint layout: ``config.json`` (architecture + full vocabulary) and
``model.safetensors`` (fp16 weights incl. ``mel_filterbank`` / ``stft_window``).

Unlike the upstream runtime, the greedy decoders here return the encoder frame
of every emitted token, so callers get word-level timestamps (one encoder frame
is ``hop_length * subsampling_factor / sample_rate`` = 40 ms).

The model was trained on utterances of up to ~25 s: callers are expected to
segment long audio (see ``mlx_gigaam_backend``) rather than feed it whole.
"""

# Adapted from misteral/GigaAM mlx_convert/gigaam_mlx.py
# (https://github.com/misteral/GigaAM/tree/feat/mlx-clean/mlx_convert) — model
# layers, log-mel front-end, checkpoint loading and SentencePiece decoding.

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mlx.core as mx
import mlx.nn as nn
import numpy as np
from server.core.stt.backends.gigaam_tokens import TimedToken, tokens_to_words

# ─────────────────────────── Config ───────────────────────────


@dataclass
class GigaAMConfig:
    model_name: str = "v3_e2e_rnnt"
    sample_rate: int = 16000
    # preprocessor
    features: int = 64
    win_length: int = 320
    hop_length: int = 160
    n_fft: int = 320
    # encoder
    feat_in: int = 64
    n_layers: int = 16
    d_model: int = 768
    subs_kernel_size: int = 5
    subsampling_factor: int = 4
    ff_expansion_factor: int = 4
    pos_emb_max_len: int = 5000
    n_heads: int = 16
    conv_kernel_size: int = 5
    # head
    head_type: str = "rnnt"
    num_classes: int = 1025
    rnnt_pred_hidden: int = 320
    rnnt_joint_hidden: int = 320
    rnnt_max_symbols: int = 10
    # vocabulary
    vocabulary: list[str] = field(default_factory=list)
    tokenizer_type: str | None = None  # None = char-wise, "sentencepiece" = E2E models
    tokenizer_control_token_ids: list[int] = field(default_factory=list)

    @property
    def frame_duration_s(self) -> float:
        """Duration of one encoder output frame, in seconds."""
        return self.hop_length * self.subsampling_factor / self.sample_rate

    @property
    def blank_id(self) -> int:
        return len(self.vocabulary)

    @classmethod
    def from_file(cls, path: Path) -> GigaAMConfig:
        d: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if d.get("model_type", "gigaam") != "gigaam":
            raise ValueError(f"Not a GigaAM checkpoint (model_type={d.get('model_type')!r})")
        enc = d.get("encoder", {})
        pre = d.get("preprocessor", {})
        head = d.get("head", {})
        head_type = d.get("head_type") or head.get("type") or "ctc"
        if head_type == "rnnt":
            num_classes = head.get("decoder", {}).get("num_classes")
        else:
            num_classes = head.get("num_classes")
        vocabulary = d.get("vocabulary")
        if not vocabulary:
            raise ValueError(
                "GigaAM config.json has no 'vocabulary' list — only the "
                "al-bo/gigaam-v3-*-mlx checkpoint layout is supported"
            )
        if self_attention := enc.get("self_attention_model"):
            if self_attention != "rotary":
                raise ValueError(f"Unsupported GigaAM attention type: {self_attention}")
        return cls(
            model_name=d.get("model_name", "v3_e2e_rnnt"),
            sample_rate=d.get("sample_rate", 16000),
            features=pre.get("features", 64),
            win_length=pre.get("win_length", 320),
            hop_length=pre.get("hop_length", 160),
            n_fft=pre.get("n_fft", 320),
            feat_in=enc.get("feat_in", 64),
            n_layers=enc.get("n_layers", 16),
            d_model=enc.get("d_model", 768),
            subs_kernel_size=enc.get("subs_kernel_size", 5),
            subsampling_factor=enc.get("subsampling_factor", 4),
            ff_expansion_factor=enc.get("ff_expansion_factor", 4),
            pos_emb_max_len=enc.get("pos_emb_max_len", 5000),
            n_heads=enc.get("n_heads", 16),
            conv_kernel_size=enc.get("conv_kernel_size", 5),
            head_type=head_type,
            num_classes=int(num_classes or len(vocabulary) + 1),
            rnnt_pred_hidden=head.get("decoder", {}).get("pred_hidden", 320),
            rnnt_joint_hidden=head.get("joint", {}).get("joint_hidden", 320),
            vocabulary=list(vocabulary),
            tokenizer_type=d.get("tokenizer_type"),
            tokenizer_control_token_ids=list(d.get("tokenizer_control_token_ids", [])),
        )


# ─────────────────────── Audio front-end ───────────────────────


def _log_mel_spectrogram(
    audio: mx.array, cfg: GigaAMConfig, mel_fb: mx.array, window: mx.array
) -> mx.array:
    """Log-mel spectrogram matching GigaAM's FeatureExtractor (center=False)."""
    n_frames = 1 + (audio.shape[-1] - cfg.win_length) // cfg.hop_length
    indices = mx.arange(cfg.win_length)[None, :] + (mx.arange(n_frames) * cfg.hop_length)[:, None]
    frames = audio[indices] * window[None, :]
    if cfg.win_length < cfg.n_fft:
        frames = mx.pad(frames, ((0, 0), (0, cfg.n_fft - cfg.win_length)))
    power = mx.square(mx.abs(mx.fft.rfft(frames)))
    return mx.log(mx.clip(power @ mel_fb, 1e-9, 1e9))  # [T, n_mels]


def _hann_window(size: int) -> mx.array:
    n = np.arange(size, dtype=np.float32)
    return mx.array(0.5 - 0.5 * np.cos(2.0 * np.pi * n / size))


# ─────────────────────── Model layers ───────────────────────


class Conv1dSubsampling(nn.Module):
    def __init__(self, cfg: GigaAMConfig):
        super().__init__()
        ks = cfg.subs_kernel_size
        pad = (ks - 1) // 2
        layers: list[nn.Module] = []
        in_ch = cfg.feat_in
        for _ in range(int(math.log2(cfg.subsampling_factor))):
            layers.append(nn.Conv1d(in_ch, cfg.d_model, kernel_size=ks, stride=2, padding=pad))
            layers.append(nn.ReLU())
            in_ch = cfg.d_model
        self.conv = layers

    def __call__(self, x: mx.array) -> mx.array:
        for layer in self.conv:
            x = layer(x)
        return x


class RotaryPositionalEmbedding(nn.Module):
    def __init__(self, dim: int, base: int):
        super().__init__()
        self._inv_freq = mx.array(1.0 / (base ** (np.arange(0, dim, 2, dtype=np.float32) / dim)))

    def __call__(self, seq_len: int) -> tuple[mx.array, mx.array]:
        freqs = mx.outer(mx.arange(seq_len).astype(mx.float32), self._inv_freq)
        emb = mx.concatenate([freqs, freqs], axis=-1)
        return mx.cos(emb), mx.sin(emb)


def _rotate_half(x: mx.array) -> mx.array:
    d = x.shape[-1] // 2
    return mx.concatenate([-x[..., d:], x[..., :d]], axis=-1)


class RotaryMultiHeadAttention(nn.Module):
    """MHA with RoPE applied to the raw input *before* the Q/K projections."""

    def __init__(self, d_model: int, n_heads: int):
        super().__init__()
        self.n_heads = n_heads
        self.d_k = d_model // n_heads
        self.linear_q = nn.Linear(d_model, d_model)
        self.linear_k = nn.Linear(d_model, d_model)
        self.linear_v = nn.Linear(d_model, d_model)
        self.linear_out = nn.Linear(d_model, d_model)

    def __call__(self, x: mx.array, cos: mx.array, sin: mx.array) -> mx.array:
        B, T, D = x.shape
        H, d_k = self.n_heads, self.d_k
        x_heads = x.reshape(B, T, H, d_k)
        rotated = (
            x_heads * cos[None, :, None, :] + _rotate_half(x_heads) * sin[None, :, None, :]
        ).reshape(B, T, D)
        q = self.linear_q(rotated).reshape(B, T, H, d_k).transpose(0, 2, 1, 3)
        k = self.linear_k(rotated).reshape(B, T, H, d_k).transpose(0, 2, 1, 3)
        v = self.linear_v(x).reshape(B, T, H, d_k).transpose(0, 2, 1, 3)
        out = mx.fast.scaled_dot_product_attention(q, k, v, scale=1.0 / math.sqrt(d_k))
        return self.linear_out(out.transpose(0, 2, 1, 3).reshape(B, T, D))


class ConformerConvolution(nn.Module):
    def __init__(self, d_model: int, kernel_size: int):
        super().__init__()
        self.pointwise_conv1 = nn.Conv1d(d_model, d_model * 2, kernel_size=1)
        self.depthwise_conv = nn.Conv1d(
            d_model,
            d_model,
            kernel_size=kernel_size,
            padding=(kernel_size - 1) // 2,
            groups=d_model,
        )
        # GigaAM v3 uses LayerNorm here (conv_norm_type=layer_norm); the
        # checkpoint keeps the upstream "batch_norm" parameter name.
        self.batch_norm = nn.LayerNorm(d_model)
        self.pointwise_conv2 = nn.Conv1d(d_model, d_model, kernel_size=1)

    def __call__(self, x: mx.array) -> mx.array:
        x = self.pointwise_conv1(x)
        half = x.shape[-1] // 2
        x = x[..., :half] * mx.sigmoid(x[..., half:])  # GLU
        x = nn.silu(self.batch_norm(self.depthwise_conv(x)))
        return self.pointwise_conv2(x)


class ConformerFeedForward(nn.Module):
    def __init__(self, d_model: int, d_ff: int):
        super().__init__()
        self.linear1 = nn.Linear(d_model, d_ff)
        self.linear2 = nn.Linear(d_ff, d_model)

    def __call__(self, x: mx.array) -> mx.array:
        return self.linear2(nn.silu(self.linear1(x)))


class ConformerLayer(nn.Module):
    def __init__(self, cfg: GigaAMConfig):
        super().__init__()
        d = cfg.d_model
        d_ff = d * cfg.ff_expansion_factor
        self.norm_feed_forward1 = nn.LayerNorm(d)
        self.feed_forward1 = ConformerFeedForward(d, d_ff)
        self.norm_self_att = nn.LayerNorm(d)
        self.self_attn = RotaryMultiHeadAttention(d, cfg.n_heads)
        self.norm_conv = nn.LayerNorm(d)
        self.conv = ConformerConvolution(d, cfg.conv_kernel_size)
        self.norm_feed_forward2 = nn.LayerNorm(d)
        self.feed_forward2 = ConformerFeedForward(d, d_ff)
        self.norm_out = nn.LayerNorm(d)

    def __call__(self, x: mx.array, cos: mx.array, sin: mx.array) -> mx.array:
        x = x + 0.5 * self.feed_forward1(self.norm_feed_forward1(x))
        x = x + self.self_attn(self.norm_self_att(x), cos, sin)
        x = x + self.conv(self.norm_conv(x))
        x = x + 0.5 * self.feed_forward2(self.norm_feed_forward2(x))
        return self.norm_out(x)


class ConformerEncoder(nn.Module):
    def __init__(self, cfg: GigaAMConfig):
        super().__init__()
        self.pre_encode = Conv1dSubsampling(cfg)
        # Upstream builds RotaryPositionalEmbedding(d_model // n_heads, pos_emb_max_len)
        # whose second positional parameter is the RoPE *base*: 5000, not 10000.
        self.pos_enc = RotaryPositionalEmbedding(cfg.d_model // cfg.n_heads, cfg.pos_emb_max_len)
        self.layers = [ConformerLayer(cfg) for _ in range(cfg.n_layers)]

    def __call__(self, features: mx.array) -> mx.array:
        x = self.pre_encode(features)
        cos, sin = self.pos_enc(x.shape[1])
        for layer in self.layers:
            x = layer(x, cos, sin)
        return x


class RNNTJoint(nn.Module):
    def __init__(self, enc_hidden: int, pred_hidden: int, joint_hidden: int, num_classes: int):
        super().__init__()
        self.enc = nn.Linear(enc_hidden, joint_hidden)
        self.pred = nn.Linear(pred_hidden, joint_hidden)
        self.joint_net_linear = nn.Linear(joint_hidden, num_classes)


class RNNTDecoder(nn.Module):
    def __init__(self, num_classes: int, pred_hidden: int):
        super().__init__()
        self.pred_hidden = pred_hidden
        self.embed = nn.Embedding(num_classes, pred_hidden)
        self.lstm = nn.LSTM(pred_hidden, pred_hidden)

    def step(
        self, label: int | None, state: tuple[mx.array, mx.array] | None
    ) -> tuple[mx.array, tuple[mx.array, mx.array]]:
        """One prediction-network step. Returns ([pred_hidden], new_state)."""
        if label is None:
            emb = mx.zeros((1, 1, self.pred_hidden))
        else:
            emb = self.embed(mx.array([[label]]))
        hidden, cell = state if state is not None else (None, None)
        out, cell_out = self.lstm(emb, hidden=hidden, cell=cell)
        return out[0, -1, :], (out[:, -1, :], cell_out[:, -1, :])


class RNNTHead(nn.Module):
    def __init__(self, cfg: GigaAMConfig):
        super().__init__()
        self.decoder = RNNTDecoder(cfg.num_classes, cfg.rnnt_pred_hidden)
        self.joint = RNNTJoint(
            cfg.d_model, cfg.rnnt_pred_hidden, cfg.rnnt_joint_hidden, cfg.num_classes
        )


class CTCHead(nn.Module):
    def __init__(self, cfg: GigaAMConfig):
        super().__init__()
        self.decoder_layers = [nn.Conv1d(cfg.d_model, cfg.num_classes, kernel_size=1)]

    def __call__(self, x: mx.array) -> mx.array:
        return self.decoder_layers[0](x)


# ─────────────────────── Full model ───────────────────────


def _softmax_prob(logits: np.ndarray, index: int) -> float:
    shifted = logits - logits.max()
    exp = np.exp(shifted)
    return float(exp[index] / exp.sum())


class GigaAM(nn.Module):
    """GigaAM v3 ASR model (CTC or RNN-T head)."""

    def __init__(self, cfg: GigaAMConfig):
        super().__init__()
        self.cfg = cfg
        self.encoder = ConformerEncoder(cfg)
        self.head = RNNTHead(cfg) if cfg.head_type == "rnnt" else CTCHead(cfg)
        self.mel_filterbank: mx.array | None = None
        self.stft_window: mx.array | None = None

    def encode(self, audio: np.ndarray) -> mx.array:
        """16 kHz mono float32 waveform → encoder output [T', d_model]."""
        cfg = self.cfg
        if audio.shape[0] < cfg.win_length:
            audio = np.pad(audio, (0, cfg.win_length - audio.shape[0]))
        window = self.stft_window if self.stft_window is not None else _hann_window(cfg.win_length)
        if self.mel_filterbank is None:
            raise RuntimeError("GigaAM checkpoint has no mel_filterbank tensor")
        mel = _log_mel_spectrogram(mx.array(audio), cfg, self.mel_filterbank, window)
        return self.encoder(mel[None, :, :])[0]

    def transcribe_tokens(self, audio: np.ndarray) -> list[TimedToken]:
        """Greedy-decode one utterance (≤ ~25 s) into timed tokens."""
        encoded = self.encode(audio)
        if self.cfg.head_type == "rnnt":
            return self._rnnt_greedy(encoded)
        return self._ctc_greedy(encoded)

    def _ctc_greedy(self, encoded: mx.array) -> list[TimedToken]:
        logits = self.head(encoded[None])[0]
        mx.eval(logits)
        logits_np = np.array(logits, dtype=np.float32)
        labels = logits_np.argmax(axis=-1)
        blank = self.cfg.blank_id
        tokens: list[TimedToken] = []
        prev = -1
        for t, label in enumerate(labels.tolist()):
            if label != blank and label != prev:
                tokens.append(TimedToken(label, t, _softmax_prob(logits_np[t], label)))
            prev = label
        return tokens

    def _rnnt_greedy(self, encoded: mx.array) -> list[TimedToken]:
        """Frame-synchronous greedy RNN-T decoding.

        The joint network is ``Linear(relu(enc(f_t) + pred(g_u)))``: the encoder
        projection is computed once for all frames on the GPU, and the
        prediction-network output only changes when a token is emitted, so the
        per-frame work is a small CPU mat-vec instead of a GPU round-trip.
        """
        head = self.head
        joint = head.joint
        enc_proj = joint.enc(encoded)
        w_out = joint.joint_net_linear.weight
        b_out = joint.joint_net_linear.bias
        mx.eval(enc_proj, w_out, b_out)
        enc_np = np.array(enc_proj, dtype=np.float32)
        w_np = np.array(w_out, dtype=np.float32).T  # [joint_hidden, num_classes]
        b_np = np.array(b_out, dtype=np.float32)

        blank = self.cfg.blank_id
        max_symbols = self.cfg.rnnt_max_symbols

        def predict(label: int | None, state: Any) -> tuple[np.ndarray, Any]:
            g, new_state = head.decoder.step(label, state)
            pred = joint.pred(g)
            mx.eval(pred, new_state)
            return np.array(pred, dtype=np.float32), new_state

        pred_np, candidate_state = predict(None, None)
        dec_state = None
        tokens: list[TimedToken] = []
        for t in range(enc_np.shape[0]):
            for _ in range(max_symbols):
                logits = np.maximum(enc_np[t] + pred_np, 0.0) @ w_np + b_np
                k = int(logits.argmax())
                if k == blank:
                    break
                tokens.append(TimedToken(k, t, _softmax_prob(logits, k)))
                dec_state = candidate_state
                pred_np, candidate_state = predict(k, dec_state)
        return tokens

    def tokens_to_words(
        self, tokens: list[TimedToken], offset_s: float = 0.0
    ) -> list[dict[str, Any]]:
        """Group timed tokens into ``{"word", "start", "end", "probability"}`` dicts."""
        cfg = self.cfg
        return tokens_to_words(
            tokens,
            cfg.vocabulary,
            sentencepiece=cfg.tokenizer_type == "sentencepiece",
            frame_duration_s=cfg.frame_duration_s,
            offset_s=offset_s,
            control_token_ids=cfg.tokenizer_control_token_ids,
        )


def load_model(model_dir: str | Path) -> GigaAM:
    """Load an ``al-bo/gigaam-v3-*-mlx`` checkpoint directory.

    Weights are upcast to float32 once: activations are float32 anyway (the
    log-mel input is fp32), and fp16 weights would cost a cast on every op.
    """
    model_dir = Path(model_dir)
    cfg = GigaAMConfig.from_file(model_dir / "config.json")
    weights_path = model_dir / "model.safetensors"
    if not weights_path.exists():
        raise FileNotFoundError(
            f"{weights_path} not found — only the al-bo/gigaam-v3-*-mlx checkpoint "
            "layout (model.safetensors with embedded mel filterbank) is supported"
        )
    model = GigaAM(cfg)
    weights = mx.load(str(weights_path))
    mel_fb = weights.pop("mel_filterbank", None)
    stft_win = weights.pop("stft_window", None)
    weights = {k: v.astype(mx.float32) for k, v in weights.items()}
    model.load_weights(list(weights.items()), strict=True)
    if mel_fb is not None:
        model.mel_filterbank = mel_fb.astype(mx.float32)
    if stft_win is not None:
        model.stft_window = stft_win.astype(mx.float32)
    mx.eval(model.parameters())
    return model
