"""
LSTM encoder-decoder with attention for multi-step journey prediction.

Architecture:
  - JourneyEncoder: Embedding -> LSTM encoder producing hidden states.
  - AttentionLayer: Bahdanau (additive) attention over encoder outputs.
  - JourneyDecoder: Embedding + Attention + LSTM -> Linear(vocab_size).
  - JourneyPrediction: AetherModel wrapper handling vocab, training with
    teacher forcing, and autoregressive multi-step prediction.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score

from common.src.base import AetherModel, DeploymentTarget, ModelMetadata, ModelType

logger = logging.getLogger("aether.ml.server.journey")

# Special tokens
PAD_TOKEN = "<PAD>"
SOS_TOKEN = "<SOS>"
EOS_TOKEN = "<EOS>"
UNK_TOKEN = "<UNK>"
SPECIAL_TOKENS: list[str] = [PAD_TOKEN, SOS_TOKEN, EOS_TOKEN, UNK_TOKEN]


# =============================================================================
# ENCODER
# =============================================================================


class JourneyEncoder(nn.Module):
    """
    LSTM encoder that maps an input event sequence to hidden states.

    Parameters
    ----------
    vocab_size : int
        Size of the event vocabulary (including special tokens).
    embed_dim : int
        Dimensionality of the event embeddings.
    hidden_dim : int
        Number of hidden units in the LSTM.
    num_layers : int
        Number of stacked LSTM layers.
    dropout : float
        Dropout probability applied between LSTM layers.
    """

    def __init__(
        self,
        vocab_size: int,
        embed_dim: int = 64,
        hidden_dim: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers

        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.lstm = nn.LSTM(
            input_size=embed_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0.0,
            batch_first=True,
        )
        self.dropout = nn.Dropout(dropout)

    def forward(
        self, x: torch.Tensor
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        """
        Parameters
        ----------
        x : torch.Tensor
            Input token IDs of shape ``(batch, seq_len)``.

        Returns
        -------
        outputs : torch.Tensor
            Encoder outputs of shape ``(batch, seq_len, hidden_dim)``.
        hidden : tuple[torch.Tensor, torch.Tensor]
            Final LSTM hidden and cell states, each of shape
            ``(num_layers, batch, hidden_dim)``.
        """
        embedded = self.dropout(self.embedding(x))  # (B, S, E)
        outputs, hidden = self.lstm(embedded)  # outputs: (B, S, H)
        return outputs, hidden


# =============================================================================
# ATTENTION
# =============================================================================


class AttentionLayer(nn.Module):
    """
    Bahdanau (additive) attention mechanism.

    Computes a context vector as a weighted sum of encoder outputs, where the
    weights are learned via a single-layer feedforward alignment model.

    Parameters
    ----------
    hidden_dim : int
        Dimensionality of both encoder outputs and decoder hidden state.
    """

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.W_encoder = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.W_decoder = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.v = nn.Linear(hidden_dim, 1, bias=False)

    def forward(
        self,
        decoder_hidden: torch.Tensor,
        encoder_outputs: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Parameters
        ----------
        decoder_hidden : torch.Tensor
            Current decoder hidden state of shape ``(batch, hidden_dim)``.
        encoder_outputs : torch.Tensor
            All encoder outputs of shape ``(batch, src_len, hidden_dim)``.

        Returns
        -------
        context_vector : torch.Tensor
            Shape ``(batch, hidden_dim)``.
        attention_weights : torch.Tensor
            Shape ``(batch, src_len)``.
        """
        # decoder_hidden: (B, H) -> (B, 1, H) for broadcasting
        decoder_proj = self.W_decoder(decoder_hidden.unsqueeze(1))  # (B, 1, H)
        encoder_proj = self.W_encoder(encoder_outputs)  # (B, S, H)

        # Alignment scores via additive attention
        energy = torch.tanh(decoder_proj + encoder_proj)  # (B, S, H)
        scores = self.v(energy).squeeze(-1)  # (B, S)

        attention_weights = torch.softmax(scores, dim=-1)  # (B, S)

        # Context is the weighted sum of encoder outputs
        context_vector = torch.bmm(
            attention_weights.unsqueeze(1), encoder_outputs
        ).squeeze(1)  # (B, H)

        return context_vector, attention_weights


# =============================================================================
# DECODER
# =============================================================================


class JourneyDecoder(nn.Module):
    """
    LSTM decoder with Bahdanau attention for autoregressive event generation.

    At each time step the decoder receives:
      - The embedding of the previous token (or ground-truth during teacher
        forcing).
      - A context vector produced by the attention layer over encoder outputs.

    Parameters
    ----------
    vocab_size : int
        Size of the output vocabulary.
    embed_dim : int
        Dimensionality of the token embeddings.
    hidden_dim : int
        Number of hidden units in the LSTM.
    num_layers : int
        Number of stacked LSTM layers.
    dropout : float
        Dropout probability.
    """

    def __init__(
        self,
        vocab_size: int,
        embed_dim: int = 64,
        hidden_dim: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.vocab_size = vocab_size

        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.attention = AttentionLayer(hidden_dim)

        # LSTM input = embedded token + context vector
        self.lstm = nn.LSTM(
            input_size=embed_dim + hidden_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0.0,
            batch_first=True,
        )
        self.fc_out = nn.Linear(hidden_dim, vocab_size)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        input_token: torch.Tensor,
        hidden: tuple[torch.Tensor, torch.Tensor],
        encoder_outputs: torch.Tensor,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor], torch.Tensor]:
        """
        Single-step decoder forward pass.

        Parameters
        ----------
        input_token : torch.Tensor
            Token IDs of shape ``(batch,)`` or ``(batch, 1)``.
        hidden : tuple[torch.Tensor, torch.Tensor]
            Previous LSTM hidden and cell states.
        encoder_outputs : torch.Tensor
            Encoder outputs of shape ``(batch, src_len, hidden_dim)``.

        Returns
        -------
        prediction : torch.Tensor
            Logits over the vocabulary of shape ``(batch, vocab_size)``.
        hidden : tuple[torch.Tensor, torch.Tensor]
            Updated LSTM hidden and cell states.
        attention_weights : torch.Tensor
            Attention weights of shape ``(batch, src_len)``.
        """
        if input_token.dim() == 1:
            input_token = input_token.unsqueeze(1)  # (B, 1)

        embedded = self.dropout(self.embedding(input_token))  # (B, 1, E)

        # Use the top-layer hidden state for attention
        decoder_hidden_top = hidden[0][-1]  # (B, H)
        context, attn_weights = self.attention(decoder_hidden_top, encoder_outputs)

        # Concatenate embedding with context
        lstm_input = torch.cat(
            [embedded, context.unsqueeze(1)], dim=-1
        )  # (B, 1, E+H)

        output, hidden = self.lstm(lstm_input, hidden)  # output: (B, 1, H)
        prediction = self.fc_out(output.squeeze(1))  # (B, V)

        return prediction, hidden, attn_weights


# =============================================================================
# JOURNEY PREDICTION MODEL (AetherModel wrapper)
# =============================================================================


class JourneyPrediction(AetherModel):
    """
    End-to-end journey prediction model wrapping the encoder-decoder with
    attention.

    Handles vocabulary construction, teacher-forced training, and
    autoregressive multi-step prediction with optional attention-weight
    extraction.
    """

    model_type_name: str = "journey_prediction"

    def __init__(
        self,
        vocab_size: int = 100,
        embed_dim: int = 64,
        hidden_dim: int = 128,
        max_sequence_length: int = 50,
        version: str = "1.0.0",
    ) -> None:
        super().__init__(ModelType.JOURNEY_PREDICTION, version)
        self.vocab_size = vocab_size
        self.embed_dim = embed_dim
        self.hidden_dim = hidden_dim
        self.max_sequence_length = max_sequence_length
        self.num_layers = 2
        self.dropout = 0.2

        self._encoder: Optional[JourneyEncoder] = None
        self._decoder: Optional[JourneyDecoder] = None
        self._vocab: dict[str, int] = {}
        self._idx_to_token: dict[int, str] = {}

    # --------------------------------------------------------------------- #
    # Vocabulary
    # --------------------------------------------------------------------- #

    def _build_vocab(self, sequences: list[list[str]]) -> dict[str, int]:
        """
        Build a mapping from event names to integer indices.

        Special tokens ``<PAD>``, ``<SOS>``, ``<EOS>``, and ``<UNK>`` are
        always assigned indices 0--3.

        Parameters
        ----------
        sequences : list[list[str]]
            A list of event-name sequences.

        Returns
        -------
        dict[str, int]
            Mapping from event name to integer index.
        """
        vocab: dict[str, int] = {}
        for i, token in enumerate(SPECIAL_TOKENS):
            vocab[token] = i

        idx = len(SPECIAL_TOKENS)
        for seq in sequences:
            for event in seq:
                if event not in vocab:
                    vocab[event] = idx
                    idx += 1

        self._vocab = vocab
        self._idx_to_token = {v: k for k, v in vocab.items()}
        self.vocab_size = len(vocab)
        return vocab

    def _encode_sequence(self, sequence: list[str]) -> list[int]:
        """Convert a list of event names to token indices."""
        unk_idx = self._vocab.get(UNK_TOKEN, 3)
        return [self._vocab.get(e, unk_idx) for e in sequence]

    def _decode_indices(self, indices: list[int]) -> list[str]:
        """Convert a list of token indices back to event names."""
        return [self._idx_to_token.get(i, UNK_TOKEN) for i in indices]

    # --------------------------------------------------------------------- #
    # Training
    # --------------------------------------------------------------------- #

    def train(
        self,
        X: list[list[str]],  # type: ignore[override]
        y: Any = None,
        *,
        epochs: int = 50,
        lr: float = 1e-3,
        batch_size: int = 64,
        teacher_forcing_ratio: float = 0.5,
        **kwargs: Any,
    ) -> dict[str, float]:
        """
        Build vocabulary and train the encoder-decoder with teacher forcing.

        Parameters
        ----------
        X : list[list[str]]
            Each element is a journey represented as a list of event-name
            strings (e.g. ``["page_view", "click", "conversion"]``).
        y : ignored
            Labels are derived from the sequences themselves (next-step
            prediction).
        epochs : int
            Number of training epochs.
        lr : float
            Learning rate for Adam.
        batch_size : int
            Mini-batch size.
        teacher_forcing_ratio : float
            Probability of using ground-truth tokens as decoder input during
            training.

        Returns
        -------
        dict[str, float]
            Training metrics including loss and accuracy.
        """
        import random

        # -- Build vocabulary -------------------------------------------------
        self._build_vocab(X)

        # -- Instantiate encoder and decoder ----------------------------------
        self._encoder = JourneyEncoder(
            vocab_size=self.vocab_size,
            embed_dim=self.embed_dim,
            hidden_dim=self.hidden_dim,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )
        self._decoder = JourneyDecoder(
            vocab_size=self.vocab_size,
            embed_dim=self.embed_dim,
            hidden_dim=self.hidden_dim,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )

        # -- Prepare tensor data ----------------------------------------------
        sos_idx = self._vocab[SOS_TOKEN]
        eos_idx = self._vocab[EOS_TOKEN]
        pad_idx = self._vocab[PAD_TOKEN]

        # Encode sequences and split into input (source) / target
        encoded: list[list[int]] = []
        for seq in X:
            enc = self._encode_sequence(seq)
            # Truncate to max length leaving room for SOS/EOS
            enc = enc[: self.max_sequence_length - 2]
            encoded.append(enc)

        # Source = full encoded sequence; Target = sequence shifted by one
        # with SOS prepended and EOS appended.
        src_seqs: list[list[int]] = []
        tgt_seqs: list[list[int]] = []
        for enc in encoded:
            src_seqs.append(enc)
            tgt_seqs.append([sos_idx] + enc + [eos_idx])

        # Pad to uniform length
        max_src = min(
            max((len(s) for s in src_seqs), default=1),
            self.max_sequence_length,
        )
        max_tgt = min(
            max((len(t) for t in tgt_seqs), default=1),
            self.max_sequence_length + 2,
        )

        src_padded = np.full((len(src_seqs), max_src), pad_idx, dtype=np.int64)
        tgt_padded = np.full((len(tgt_seqs), max_tgt), pad_idx, dtype=np.int64)
        for i, (s, t) in enumerate(zip(src_seqs, tgt_seqs)):
            src_padded[i, : len(s)] = s[:max_src]
            tgt_padded[i, : len(t)] = t[:max_tgt]

        src_tensor = torch.LongTensor(src_padded)
        tgt_tensor = torch.LongTensor(tgt_padded)

        # -- Optimiser & loss -------------------------------------------------
        params = list(self._encoder.parameters()) + list(self._decoder.parameters())
        optimizer = torch.optim.Adam(params, lr=lr)
        criterion = nn.CrossEntropyLoss(ignore_index=pad_idx)

        n_samples = len(src_tensor)

        # -- Training loop ----------------------------------------------------
        self._encoder.train()
        self._decoder.train()

        best_loss = float("inf")
        for epoch in range(epochs):
            # Shuffle
            perm = torch.randperm(n_samples)
            epoch_loss = 0.0
            n_batches = 0

            for start in range(0, n_samples, batch_size):
                idx = perm[start : start + batch_size]
                src_batch = src_tensor[idx]
                tgt_batch = tgt_tensor[idx]
                cur_batch_size = src_batch.size(0)
                tgt_len = tgt_batch.size(1)

                optimizer.zero_grad()

                # Encode
                encoder_outputs, hidden = self._encoder(src_batch)

                # Decode step by step
                decoder_input = tgt_batch[:, 0]  # SOS token
                outputs = torch.zeros(cur_batch_size, tgt_len - 1, self.vocab_size)

                for t in range(1, tgt_len):
                    prediction, hidden, _ = self._decoder(
                        decoder_input, hidden, encoder_outputs
                    )
                    outputs[:, t - 1] = prediction

                    # Teacher forcing
                    if random.random() < teacher_forcing_ratio:
                        decoder_input = tgt_batch[:, t]
                    else:
                        decoder_input = prediction.argmax(dim=-1)

                # Compute loss (flatten)
                loss = criterion(
                    outputs.reshape(-1, self.vocab_size),
                    tgt_batch[:, 1:].reshape(-1),
                )
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, max_norm=1.0)
                optimizer.step()

                epoch_loss += loss.item()
                n_batches += 1

            avg_loss = epoch_loss / max(n_batches, 1)
            if avg_loss < best_loss:
                best_loss = avg_loss

            if (epoch + 1) % 10 == 0:
                logger.info(f"Epoch {epoch + 1}/{epochs}: loss={avg_loss:.4f}")

        # -- Evaluation -------------------------------------------------------
        self._encoder.eval()
        self._decoder.eval()

        correct = 0
        total = 0
        with torch.no_grad():
            encoder_outputs, hidden = self._encoder(src_tensor)
            decoder_input = tgt_tensor[:, 0]
            for t in range(1, tgt_tensor.size(1)):
                prediction, hidden, _ = self._decoder(
                    decoder_input, hidden, encoder_outputs
                )
                pred_tokens = prediction.argmax(dim=-1)
                mask = tgt_tensor[:, t] != pad_idx
                correct += int(((pred_tokens == tgt_tensor[:, t]) & mask).sum().item())
                total += int(mask.sum().item())
                decoder_input = tgt_tensor[:, t]

        metrics: dict[str, float] = {
            "training_loss": best_loss,
            "next_step_accuracy": correct / max(total, 1),
            "vocab_size": float(self.vocab_size),
            "n_sequences": float(len(X)),
        }

        self.is_trained = True
        self.metadata = ModelMetadata(
            model_id=f"journey-v{self.version}",
            model_type=self.model_type,
            version=self.version,
            deployment_target=DeploymentTarget.SERVER_SAGEMAKER,
            metrics=metrics,
            feature_columns=[],
            training_data_hash="",
            hyperparameters={
                "vocab_size": self.vocab_size,
                "embed_dim": self.embed_dim,
                "hidden_dim": self.hidden_dim,
                "num_layers": self.num_layers,
                "epochs": epochs,
                "lr": lr,
                "max_sequence_length": self.max_sequence_length,
            },
        )
        return metrics

    # --------------------------------------------------------------------- #
    # Prediction
    # --------------------------------------------------------------------- #

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Thin wrapper satisfying the ``AetherModel`` interface.

        Expects *X* to contain a column ``"sequence"`` where each cell is a
        list of event-name strings.  Returns the predicted next event for each
        row.
        """
        if not self.is_trained:
            raise RuntimeError("Model has not been trained yet.")

        results: list[str] = []
        for _, row in X.iterrows():
            seq: list[str] = row["sequence"] if "sequence" in row.index else []
            preds = self._predict_sequence(seq, n_steps=1)
            results.append(preds[0] if preds else UNK_TOKEN)
        return np.array(results)

    def _predict_sequence(
        self, sequence: list[str], n_steps: int = 5
    ) -> list[str]:
        """Auto-regressively predict the next *n_steps* events."""
        assert self._encoder is not None and self._decoder is not None

        sos_idx = self._vocab[SOS_TOKEN]
        eos_idx = self._vocab[EOS_TOKEN]
        pad_idx = self._vocab[PAD_TOKEN]

        encoded = self._encode_sequence(sequence)
        src = torch.LongTensor([encoded])  # (1, S)

        self._encoder.eval()
        self._decoder.eval()

        with torch.no_grad():
            encoder_outputs, hidden = self._encoder(src)
            decoder_input = torch.LongTensor([sos_idx])

            predicted: list[str] = []
            for _ in range(n_steps):
                prediction, hidden, _ = self._decoder(
                    decoder_input, hidden, encoder_outputs
                )
                top_token = prediction.argmax(dim=-1).item()

                if top_token == eos_idx or top_token == pad_idx:
                    break

                event_name = self._idx_to_token.get(top_token, UNK_TOKEN)
                predicted.append(event_name)
                decoder_input = torch.LongTensor([top_token])

        return predicted

    def predict_with_attention(
        self, sequence: list[str], n_steps: int = 5
    ) -> tuple[list[str], np.ndarray]:
        """
        Predict next events and return the attention weights at each step.

        Parameters
        ----------
        sequence : list[str]
            The observed event sequence.
        n_steps : int
            Number of future steps to generate.

        Returns
        -------
        predicted_events : list[str]
            The predicted event names.
        attention_matrix : np.ndarray
            Array of shape ``(n_predicted_steps, src_len)`` containing the
            attention weights the decoder placed on each encoder position.
        """
        assert self._encoder is not None and self._decoder is not None

        sos_idx = self._vocab[SOS_TOKEN]
        eos_idx = self._vocab[EOS_TOKEN]
        pad_idx = self._vocab[PAD_TOKEN]

        encoded = self._encode_sequence(sequence)
        src = torch.LongTensor([encoded])  # (1, S)

        self._encoder.eval()
        self._decoder.eval()

        predicted: list[str] = []
        all_attn: list[np.ndarray] = []

        with torch.no_grad():
            encoder_outputs, hidden = self._encoder(src)
            decoder_input = torch.LongTensor([sos_idx])

            for _ in range(n_steps):
                prediction, hidden, attn_weights = self._decoder(
                    decoder_input, hidden, encoder_outputs
                )
                top_token = prediction.argmax(dim=-1).item()

                if top_token == eos_idx or top_token == pad_idx:
                    break

                event_name = self._idx_to_token.get(top_token, UNK_TOKEN)
                predicted.append(event_name)
                all_attn.append(attn_weights.squeeze(0).numpy())
                decoder_input = torch.LongTensor([top_token])

        attention_matrix = (
            np.stack(all_attn) if all_attn else np.empty((0, len(encoded)))
        )
        return predicted, attention_matrix

    # --------------------------------------------------------------------- #
    # Persistence
    # --------------------------------------------------------------------- #

    def save(self, path: Path) -> None:
        import json

        path.mkdir(parents=True, exist_ok=True)
        if self._encoder is not None:
            torch.save(self._encoder.state_dict(), path / "encoder.pt")
        if self._decoder is not None:
            torch.save(self._decoder.state_dict(), path / "decoder.pt")

        (path / "vocab.json").write_text(json.dumps(self._vocab, indent=2))
        (path / "config.json").write_text(
            json.dumps(
                {
                    "vocab_size": self.vocab_size,
                    "embed_dim": self.embed_dim,
                    "hidden_dim": self.hidden_dim,
                    "num_layers": self.num_layers,
                    "dropout": self.dropout,
                    "max_sequence_length": self.max_sequence_length,
                },
                indent=2,
            )
        )
        if self.metadata:
            (path / "metadata.json").write_text(self.metadata.model_dump_json(indent=2))
        logger.info(f"Saved journey prediction model to {path}")

    def load(self, path: Path) -> None:
        import json

        config = json.loads((path / "config.json").read_text())
        self.vocab_size = config["vocab_size"]
        self.embed_dim = config["embed_dim"]
        self.hidden_dim = config["hidden_dim"]
        self.num_layers = config["num_layers"]
        self.dropout = config["dropout"]
        self.max_sequence_length = config["max_sequence_length"]

        self._vocab = json.loads((path / "vocab.json").read_text())
        # JSON keys are always strings; ensure integer values
        self._vocab = {k: int(v) for k, v in self._vocab.items()}
        self._idx_to_token = {v: k for k, v in self._vocab.items()}

        self._encoder = JourneyEncoder(
            vocab_size=self.vocab_size,
            embed_dim=self.embed_dim,
            hidden_dim=self.hidden_dim,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )
        self._decoder = JourneyDecoder(
            vocab_size=self.vocab_size,
            embed_dim=self.embed_dim,
            hidden_dim=self.hidden_dim,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )

        self._encoder.load_state_dict(
            torch.load(path / "encoder.pt", weights_only=True)
        )
        self._decoder.load_state_dict(
            torch.load(path / "decoder.pt", weights_only=True)
        )
        self._encoder.eval()
        self._decoder.eval()

        if (path / "metadata.json").exists():
            self.metadata = ModelMetadata.model_validate_json(
                (path / "metadata.json").read_text()
            )
        self.is_trained = True
        logger.info(f"Loaded journey prediction model from {path}")

    def _compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {"accuracy": float(accuracy_score(y_true, y_pred))}
