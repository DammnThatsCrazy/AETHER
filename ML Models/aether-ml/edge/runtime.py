"""
Aether ML — Edge Inference Runtime
Lightweight inference runtime for edge-deployed models.
Supports ONNX (via onnxruntime), sklearn (via joblib), and TFLite formats.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
import os
import time
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np

logger = logging.getLogger("aether.ml.edge.runtime")


class EdgeInferenceRuntime:
    """
    Lightweight inference runtime for edge-deployed models.

    Detects model format from file extension and loads the appropriate backend:
      - .onnx  -> ONNX Runtime (onnxruntime)
      - .pkl   -> scikit-learn / joblib
      - .tflite -> TensorFlow Lite

    Usage::

        runtime = EdgeInferenceRuntime("models/bot_model.onnx")
        runtime.load()
        runtime.warmup(n=5)
        result = runtime.predict({"mouse_speed_mean": 1.2, "click_interval_mean": 0.5, ...})
        print(result)  # {"prediction": ..., "latency_ms": 2.31, "model_info": {...}}
    """

    _SUPPORTED_EXTENSIONS: dict[str, str] = {
        ".onnx": "onnx",
        ".pkl": "sklearn",
        ".tflite": "tflite",
    }

    def __init__(self, model_path: str, runtime: str = "auto") -> None:
        """
        Initialize the edge inference runtime.

        Args:
            model_path: Path to the model file (.onnx, .pkl, or .tflite).
            runtime: Runtime backend to use. One of "auto", "onnx", "sklearn",
                     or "tflite". When "auto", the format is detected from the
                     file extension.
        """
        self.model_path: str = model_path
        self._requested_runtime: str = runtime
        self._format: Optional[str] = None
        self._model: Any = None
        self._onnx_session: Any = None
        self._tflite_interpreter: Any = None
        self._is_loaded: bool = False
        self._feature_names: Optional[list[str]] = None

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def load(self) -> None:
        """
        Detect model format from the file extension and load the model.

        Raises:
            FileNotFoundError: If the model file does not exist.
            ValueError: If the file extension is not supported and runtime is 'auto'.
        """
        path = Path(self.model_path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")

        # Resolve format
        if self._requested_runtime == "auto":
            ext = path.suffix.lower()
            if ext not in self._SUPPORTED_EXTENSIONS:
                raise ValueError(
                    f"Unsupported model extension '{ext}'. "
                    f"Expected one of: {list(self._SUPPORTED_EXTENSIONS.keys())}"
                )
            self._format = self._SUPPORTED_EXTENSIONS[ext]
        else:
            self._format = self._requested_runtime

        # Dispatch to format-specific loader
        if self._format == "onnx":
            self._load_onnx()
        elif self._format == "sklearn":
            self._load_sklearn()
        elif self._format == "tflite":
            self._load_tflite()
        else:
            raise ValueError(f"Unsupported runtime: {self._format}")

        self._is_loaded = True
        logger.info(
            "EdgeInferenceRuntime loaded model '%s' (format=%s)",
            self.model_path,
            self._format,
        )

    def predict(self, features: Union[dict[str, Any], np.ndarray]) -> dict[str, Any]:
        """
        Run inference on the loaded model.

        Args:
            features: Either a dict mapping feature names to values, or a
                      numpy array of shape (n_features,) or (1, n_features).

        Returns:
            Dictionary with keys:
              - "prediction": The model output (class label, probabilities, etc.).
              - "latency_ms": Inference latency in milliseconds.
              - "model_info": Dict with format, size_bytes, and feature_names.
        """
        if not self._is_loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        # Convert dict to numpy array
        if isinstance(features, dict):
            self._feature_names = list(features.keys())
            feature_array = np.array(
                [list(features.values())], dtype=np.float32
            )
        elif isinstance(features, np.ndarray):
            feature_array = features.astype(np.float32)
            if feature_array.ndim == 1:
                feature_array = feature_array.reshape(1, -1)
        else:
            raise TypeError(
                f"features must be dict or np.ndarray, got {type(features)}"
            )

        start = time.monotonic()

        if self._format == "onnx":
            prediction = self._predict_onnx(feature_array)
        elif self._format == "sklearn":
            prediction = self._predict_sklearn(feature_array)
        elif self._format == "tflite":
            prediction = self._predict_tflite(feature_array)
        else:
            raise RuntimeError(f"Unknown format: {self._format}")

        latency_ms = (time.monotonic() - start) * 1000

        return {
            "prediction": prediction,
            "latency_ms": round(latency_ms, 4),
            "model_info": self.get_model_info(),
        }

    def warmup(self, n: int = 5) -> None:
        """
        Run n dummy predictions to warm up JIT compilation and caches.

        Args:
            n: Number of warmup iterations (default: 5).
        """
        if not self._is_loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        n_features = self._infer_n_features()
        dummy = np.random.randn(1, n_features).astype(np.float32)

        for _ in range(n):
            if self._format == "onnx":
                self._predict_onnx(dummy)
            elif self._format == "sklearn":
                self._predict_sklearn(dummy)
            elif self._format == "tflite":
                self._predict_tflite(dummy)

        logger.info("Warmup complete (%d iterations)", n)

    def benchmark(self, n: int = 100) -> dict[str, float]:
        """
        Run n predictions and compute latency percentiles.

        Args:
            n: Number of benchmark iterations (default: 100).

        Returns:
            Dictionary with p50, p95, p99 latency in milliseconds, plus
            mean and min/max.
        """
        if not self._is_loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        n_features = self._infer_n_features()
        dummy = np.random.randn(1, n_features).astype(np.float32)
        latencies: list[float] = []

        for _ in range(n):
            start = time.monotonic()
            if self._format == "onnx":
                self._predict_onnx(dummy)
            elif self._format == "sklearn":
                self._predict_sklearn(dummy)
            elif self._format == "tflite":
                self._predict_tflite(dummy)
            elapsed_ms = (time.monotonic() - start) * 1000
            latencies.append(elapsed_ms)

        arr = np.array(latencies)
        return {
            "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
            "mean": float(np.mean(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "n": n,
        }

    def get_model_info(self) -> dict[str, Any]:
        """
        Return metadata about the loaded model.

        Returns:
            Dictionary with format, size_bytes, and feature_names.
        """
        size_bytes: int = 0
        model_file = Path(self.model_path)
        if model_file.exists():
            size_bytes = os.path.getsize(self.model_path)

        return {
            "format": self._format,
            "size_bytes": size_bytes,
            "feature_names": self._feature_names,
        }

    # =========================================================================
    # PRIVATE — LOADERS
    # =========================================================================

    def _load_onnx(self) -> None:
        """Load an ONNX model via onnxruntime."""
        import onnxruntime as ort

        self._onnx_session = ort.InferenceSession(
            self.model_path,
            providers=["CPUExecutionProvider"],
        )
        # Extract feature names from input metadata if available
        input_meta = self._onnx_session.get_inputs()[0]
        if input_meta.name:
            self._feature_names = self._feature_names or None
        logger.info("ONNX session created: %s", self.model_path)

    def _load_sklearn(self) -> None:
        """Load a scikit-learn model via joblib."""
        import joblib

        self._model = joblib.load(self.model_path)
        logger.info("sklearn model loaded: %s", self.model_path)

    def _load_tflite(self) -> None:
        """Load a TFLite model."""
        try:
            import tflite_runtime.interpreter as tflite  # type: ignore[import-untyped]

            self._tflite_interpreter = tflite.Interpreter(
                model_path=self.model_path
            )
        except ImportError:
            import tensorflow as tf

            self._tflite_interpreter = tf.lite.Interpreter(
                model_path=self.model_path
            )
        self._tflite_interpreter.allocate_tensors()
        logger.info("TFLite model loaded: %s", self.model_path)

    # =========================================================================
    # PRIVATE — INFERENCE
    # =========================================================================

    def _predict_onnx(self, features: np.ndarray) -> Any:
        """
        Run ONNX Runtime inference.

        Args:
            features: numpy array of shape (1, n_features), dtype float32.

        Returns:
            Model output (list or numpy array, depending on the ONNX model).
        """
        if self._onnx_session is None:
            raise RuntimeError("ONNX session not initialized.")

        input_name = self._onnx_session.get_inputs()[0].name
        output_names = [o.name for o in self._onnx_session.get_outputs()]

        results = self._onnx_session.run(
            output_names,
            {input_name: features},
        )

        # Return a dict if multiple outputs, otherwise unwrap single output
        if len(results) == 1:
            result = results[0]
            return result.tolist() if isinstance(result, np.ndarray) else result
        return {
            name: (r.tolist() if isinstance(r, np.ndarray) else r)
            for name, r in zip(output_names, results)
        }

    def _predict_sklearn(self, features: np.ndarray) -> Any:
        """
        Run scikit-learn / joblib model inference.

        Args:
            features: numpy array of shape (1, n_features), dtype float32.

        Returns:
            Dictionary with 'label' and optionally 'probabilities'.
        """
        if self._model is None:
            raise RuntimeError("sklearn model not initialized.")

        prediction = self._model.predict(features)
        result: dict[str, Any] = {
            "label": prediction.tolist()
            if isinstance(prediction, np.ndarray)
            else prediction,
        }

        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba(features)
            result["probabilities"] = (
                proba.tolist() if isinstance(proba, np.ndarray) else proba
            )

        return result

    def _predict_tflite(self, features: np.ndarray) -> Any:
        """
        Run TFLite interpreter inference.

        Args:
            features: numpy array of shape (1, n_features), dtype float32.

        Returns:
            Model output tensor(s) as a list or dict.
        """
        if self._tflite_interpreter is None:
            raise RuntimeError("TFLite interpreter not initialized.")

        input_details = self._tflite_interpreter.get_input_details()
        output_details = self._tflite_interpreter.get_output_details()

        self._tflite_interpreter.set_tensor(
            input_details[0]["index"], features
        )
        self._tflite_interpreter.invoke()

        if len(output_details) == 1:
            tensor = self._tflite_interpreter.get_tensor(
                output_details[0]["index"]
            )
            return tensor.tolist() if isinstance(tensor, np.ndarray) else tensor

        outputs: dict[str, Any] = {}
        for detail in output_details:
            tensor = self._tflite_interpreter.get_tensor(detail["index"])
            outputs[detail["name"]] = (
                tensor.tolist() if isinstance(tensor, np.ndarray) else tensor
            )
        return outputs

    # =========================================================================
    # PRIVATE — UTILITIES
    # =========================================================================

    def _infer_n_features(self) -> int:
        """Infer the number of input features from the loaded model."""
        if self._format == "onnx" and self._onnx_session is not None:
            shape = self._onnx_session.get_inputs()[0].shape
            if len(shape) > 1 and isinstance(shape[1], int):
                return shape[1]

        if self._format == "sklearn" and self._model is not None:
            if hasattr(self._model, "n_features_in_"):
                return int(self._model.n_features_in_)

        if self._format == "tflite" and self._tflite_interpreter is not None:
            input_details = self._tflite_interpreter.get_input_details()
            shape = input_details[0]["shape"]
            if len(shape) > 1:
                return int(shape[1])

        # Fallback: use stored feature names count or default
        if self._feature_names:
            return len(self._feature_names)
        return 10  # conservative default for edge models


@dataclass
class EdgeRuntimeConfig:
    model_path: str = ''
    runtime: str = 'auto'
    max_latency_ms: float = 100.0


@dataclass
class EdgePrediction:
    outputs: dict[str, Any]
    latency_ms: float
    model_format: str
    error: str | None = None
    max_latency_ms: float = 100.0

    @property
    def is_valid(self) -> bool:
        return self.error is None and self.latency_ms <= self.max_latency_ms


class PredictionCache:
    def __init__(self, max_size: int = 1024, ttl_seconds: int = 300) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}

    @staticmethod
    def hash_features(features: dict[str, Any]) -> str:
        import hashlib, json
        payload = json.dumps(features, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def put(self, key: str, value: Any) -> None:
        self._entries[key] = (time.time(), value)
        while len(self._entries) > self.max_size:
            oldest = min(self._entries, key=lambda item: self._entries[item][0])
            del self._entries[oldest]

    def get(self, key: str) -> Any:
        entry = self._entries.get(key)
        if entry is None:
            return None
        created_at, value = entry
        if time.time() - created_at > self.ttl_seconds:
            del self._entries[key]
            return None
        return value

    @property
    def size(self) -> int:
        return len(self._entries)


class SklearnBackend:
    def __init__(self, model: Any) -> None:
        self.model = model


class EdgeModelManager:
    def __init__(self) -> None:
        self.models: dict[str, Any] = {}


class EdgeRuntime(EdgeInferenceRuntime):
    def __init__(self, config: EdgeRuntimeConfig | str) -> None:
        if isinstance(config, EdgeRuntimeConfig):
            super().__init__(config.model_path, runtime=config.runtime)
            self.config = config
        else:
            super().__init__(config)
            self.config = EdgeRuntimeConfig(model_path=config)
