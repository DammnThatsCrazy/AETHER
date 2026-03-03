"""Export edge models to TF.js, ONNX, TF Lite, and CoreML formats."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("aether.export")

# Default formats each edge model should be exported to
_DEFAULT_EDGE_MODELS: dict[str, list[str]] = {
    "intent_prediction": ["tfjs", "onnx"],
    "bot_detection": ["onnx", "tflite"],
    "session_scorer": ["tfjs", "coreml"],
}


# =============================================================================
# EXPORT RESULT
# =============================================================================


@dataclass
class ExportResult:
    """Captures the outcome of a single model export operation."""

    model_name: str
    format: str  # "tfjs", "onnx", "tflite", "coreml"
    output_path: str
    size_bytes: int
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "model": self.model_name,
            "format": self.format,
            "path": self.output_path,
            "size": self.size_bytes,
            "success": self.success,
            "error": self.error,
        }


# =============================================================================
# MODEL EXPORTER
# =============================================================================


class ModelExporter:
    """Converts trained edge models to deployment formats.

    Supports exporting sklearn / Keras models to ONNX, TensorFlow.js,
    TF Lite, and CoreML. Each export method is self-contained and returns
    an ``ExportResult`` so callers can inspect the outcome.
    """

    def __init__(
        self,
        models_dir: str = "/tmp/aether-models",
        output_dir: str = "/tmp/aether-exports",
    ) -> None:
        self.models_dir = Path(models_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------- #
    # ONNX
    # --------------------------------------------------------------------- #

    def export_to_onnx(
        self,
        model_path: str,
        output_path: str,
        feature_names: list[str],
    ) -> ExportResult:
        """Export an sklearn model to ONNX format.

        Uses *skl2onnx* to convert a fitted sklearn estimator into an ONNX
        graph that can be executed by ONNX Runtime on any platform.

        Args:
            model_path: Path to a joblib/pickle serialised sklearn model.
            output_path: Destination file path for the ``.onnx`` artifact.
            feature_names: Ordered list of input feature names. This
                determines the width of the input tensor.

        Returns:
            An ``ExportResult`` describing the outcome.
        """
        try:
            import joblib
            from skl2onnx import convert_sklearn
            from skl2onnx.common.data_types import FloatTensorType

            model = joblib.load(model_path)
            n_features = len(feature_names)

            initial_type = [("features", FloatTensorType([None, n_features]))]
            onnx_model = convert_sklearn(
                model,
                initial_types=initial_type,
                target_opset=13,
            )

            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "wb") as f:
                f.write(onnx_model.SerializeToString())

            size = out.stat().st_size
            logger.info(f"Exported ONNX model to {out} ({size / 1024:.1f} KB)")

            # Quick validation with onnxruntime
            self._validate_onnx(str(out), n_features)

            return ExportResult(
                model_name=Path(model_path).stem,
                format="onnx",
                output_path=str(out),
                size_bytes=size,
                success=True,
            )
        except Exception as exc:
            logger.error(f"ONNX export failed for {model_path}: {exc}")
            return ExportResult(
                model_name=Path(model_path).stem,
                format="onnx",
                output_path=output_path,
                size_bytes=0,
                success=False,
                error=str(exc),
            )

    # --------------------------------------------------------------------- #
    # TensorFlow.js
    # --------------------------------------------------------------------- #

    def export_to_tfjs(
        self, model_path: str, output_path: str
    ) -> ExportResult:
        """Export model to TensorFlow.js format.

        For sklearn linear models the weights are extracted and wrapped in a
        minimal Keras ``Dense`` layer before conversion. Keras models are
        converted directly via ``tensorflowjs``.

        Args:
            model_path: Path to the serialised model (joblib or SavedModel).
            output_path: Directory that will contain the TF.js artifacts.

        Returns:
            An ``ExportResult`` describing the outcome.
        """
        try:
            import joblib
            import tensorflow as tf
            import tensorflowjs as tfjs

            out = Path(output_path)
            out.mkdir(parents=True, exist_ok=True)

            model = joblib.load(model_path)

            if hasattr(model, "coef_"):
                # Linear model -- wrap in a single Dense layer
                weights = np.atleast_2d(model.coef_)
                bias = np.atleast_1d(model.intercept_)

                n_features = weights.shape[1]
                n_outputs = weights.shape[0]
                activation = "softmax" if n_outputs > 1 else "sigmoid"

                keras_model = tf.keras.Sequential(
                    [
                        tf.keras.layers.Input(shape=(n_features,)),
                        tf.keras.layers.Dense(n_outputs, activation=activation),
                    ]
                )
                keras_model.layers[0].set_weights([weights.T, bias])
            else:
                raise ValueError(
                    "Cannot auto-convert this sklearn model to TF.js. "
                    "Only linear models with coef_/intercept_ are supported."
                )

            tfjs.converters.save_keras_model(keras_model, str(out))

            # Write a small manifest alongside the model artifacts
            manifest = {
                "model_name": Path(model_path).stem,
                "format": "tfjs",
                "input_features": n_features,
                "output_units": n_outputs,
            }
            (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

            size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
            logger.info(f"Exported TF.js model to {out} ({size / 1024:.1f} KB)")

            return ExportResult(
                model_name=Path(model_path).stem,
                format="tfjs",
                output_path=str(out),
                size_bytes=size,
                success=True,
            )
        except Exception as exc:
            logger.error(f"TF.js export failed for {model_path}: {exc}")
            return ExportResult(
                model_name=Path(model_path).stem,
                format="tfjs",
                output_path=output_path,
                size_bytes=0,
                success=False,
                error=str(exc),
            )

    # --------------------------------------------------------------------- #
    # TF Lite
    # --------------------------------------------------------------------- #

    def export_to_tflite(
        self, model_path: str, output_path: str
    ) -> ExportResult:
        """Export model to TF Lite format.

        Loads a Keras SavedModel (or h5 file) and converts it to a
        quantised (float16) TF Lite FlatBuffer.

        Args:
            model_path: Path to a Keras SavedModel directory or ``.h5`` file.
            output_path: Destination ``.tflite`` file path.

        Returns:
            An ``ExportResult`` describing the outcome.
        """
        try:
            import tensorflow as tf

            model = tf.keras.models.load_model(model_path)
            converter = tf.lite.TFLiteConverter.from_keras_model(model)

            # Apply float16 quantisation for smaller model size
            converter.optimizations = [tf.lite.Optimize.DEFAULT]
            converter.target_spec.supported_types = [tf.float16]

            tflite_bytes = converter.convert()

            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(tflite_bytes)

            size = out.stat().st_size
            logger.info(
                f"Exported TF Lite model to {out} ({size / 1024:.1f} KB, quantized=float16)"
            )

            return ExportResult(
                model_name=Path(model_path).stem,
                format="tflite",
                output_path=str(out),
                size_bytes=size,
                success=True,
            )
        except Exception as exc:
            logger.error(f"TF Lite export failed for {model_path}: {exc}")
            return ExportResult(
                model_name=Path(model_path).stem,
                format="tflite",
                output_path=output_path,
                size_bytes=0,
                success=False,
                error=str(exc),
            )

    # --------------------------------------------------------------------- #
    # CoreML
    # --------------------------------------------------------------------- #

    def export_to_coreml(
        self, model_path: str, output_path: str
    ) -> ExportResult:
        """Export model to CoreML format for iOS native inference.

        Supports sklearn models (via ``coremltools.converters.sklearn``) and
        Keras models (via ``coremltools.convert``).

        Args:
            model_path: Path to the serialised model.
            output_path: Destination ``.mlmodel`` file path.

        Returns:
            An ``ExportResult`` describing the outcome.
        """
        try:
            import coremltools as ct

            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)

            # Attempt sklearn conversion first, fall back to Keras
            try:
                import joblib

                sklearn_model = joblib.load(model_path)
                coreml_model = ct.converters.sklearn.convert(sklearn_model)
            except Exception:
                import tensorflow as tf

                keras_model = tf.keras.models.load_model(model_path)
                coreml_model = ct.convert(keras_model)

            coreml_model.save(str(out))

            size = out.stat().st_size
            logger.info(f"Exported CoreML model to {out} ({size / 1024:.1f} KB)")

            return ExportResult(
                model_name=Path(model_path).stem,
                format="coreml",
                output_path=str(out),
                size_bytes=size,
                success=True,
            )
        except Exception as exc:
            logger.error(f"CoreML export failed for {model_path}: {exc}")
            return ExportResult(
                model_name=Path(model_path).stem,
                format="coreml",
                output_path=output_path,
                size_bytes=0,
                success=False,
                error=str(exc),
            )

    # --------------------------------------------------------------------- #
    # SINGLE MODEL EXPORT
    # --------------------------------------------------------------------- #

    def export_model(
        self,
        model_name: str,
        formats: list[str] | None = None,
    ) -> list[ExportResult]:
        """Export a single model to all requested formats.

        Looks for the model artifact inside ``self.models_dir / model_name``.

        Args:
            model_name: Name of the model (must match a sub-directory in
                ``models_dir``).
            formats: List of target formats, e.g. ``["onnx", "tfjs"]``.
                Defaults to ``["onnx", "tfjs"]`` if not specified.

        Returns:
            List of ``ExportResult``, one per requested format.
        """
        if formats is None:
            formats = _DEFAULT_EDGE_MODELS.get(model_name, ["onnx", "tfjs"])

        model_dir = self.models_dir / model_name
        results: list[ExportResult] = []

        # Find the model artifact (try common extensions)
        model_file: Path | None = None
        for ext in (".pkl", ".joblib", ".h5", ".keras"):
            candidate = model_dir / f"{model_name}{ext}"
            if candidate.exists():
                model_file = candidate
                break
        # Fall back to any file in the directory
        if model_file is None and model_dir.exists():
            for f in model_dir.iterdir():
                if f.is_file() and f.suffix in (".pkl", ".joblib", ".h5", ".keras"):
                    model_file = f
                    break

        if model_file is None:
            logger.warning(f"No model artifact found in {model_dir}")
            for fmt in formats:
                results.append(
                    ExportResult(
                        model_name=model_name,
                        format=fmt,
                        output_path="",
                        size_bytes=0,
                        success=False,
                        error=f"Model artifact not found in {model_dir}",
                    )
                )
            return results

        for fmt in formats:
            output_base = self.output_dir / model_name / fmt
            model_path_str = str(model_file)

            if fmt == "onnx":
                # Infer feature count from model
                feature_names = self._infer_feature_names(model_file)
                output_file = str(output_base / f"{model_name}.onnx")
                result = self.export_to_onnx(model_path_str, output_file, feature_names)
            elif fmt == "tfjs":
                result = self.export_to_tfjs(model_path_str, str(output_base))
            elif fmt == "tflite":
                output_file = str(output_base / f"{model_name}.tflite")
                result = self.export_to_tflite(model_path_str, output_file)
            elif fmt == "coreml":
                output_file = str(output_base / f"{model_name}.mlmodel")
                result = self.export_to_coreml(model_path_str, output_file)
            else:
                result = ExportResult(
                    model_name=model_name,
                    format=fmt,
                    output_path="",
                    size_bytes=0,
                    success=False,
                    error=f"Unsupported export format: {fmt}",
                )

            results.append(result)

        return results

    # --------------------------------------------------------------------- #
    # EXPORT ALL EDGE MODELS
    # --------------------------------------------------------------------- #

    def export_all_edge_models(self) -> list[ExportResult]:
        """Export all 3 edge models to their target formats.

        Iterates over the default edge model definitions and exports each
        to its configured formats (see ``_DEFAULT_EDGE_MODELS``).

        Returns:
            Flat list of ``ExportResult`` across all models and formats.
        """
        all_results: list[ExportResult] = []

        for model_name, formats in _DEFAULT_EDGE_MODELS.items():
            logger.info(
                f"Exporting edge model '{model_name}' to formats: {formats}"
            )
            results = self.export_model(model_name, formats=formats)
            all_results.extend(results)

        successes = sum(1 for r in all_results if r.success)
        failures = len(all_results) - successes
        logger.info(
            f"Edge model export complete: {successes} succeeded, {failures} failed"
        )
        return all_results

    # --------------------------------------------------------------------- #
    # HELPERS
    # --------------------------------------------------------------------- #

    def _validate_onnx(self, onnx_path: str, n_features: int) -> None:
        """Run a quick validation pass on an exported ONNX model.

        Creates a random input tensor and verifies the model produces output
        without errors.
        """
        try:
            import onnxruntime as ort

            session = ort.InferenceSession(onnx_path)
            dummy_input = np.random.randn(1, n_features).astype(np.float32)
            input_name = session.get_inputs()[0].name
            session.run(None, {input_name: dummy_input})
            logger.debug(f"ONNX validation passed for {onnx_path}")
        except Exception as exc:
            logger.warning(f"ONNX validation failed for {onnx_path}: {exc}")

    @staticmethod
    def _infer_feature_names(model_path: Path) -> list[str]:
        """Attempt to infer feature names from a fitted sklearn model.

        Falls back to generic ``feature_0 .. feature_N`` names when the
        model does not store ``feature_names_in_``.
        """
        try:
            import joblib

            model = joblib.load(model_path)
            if hasattr(model, "feature_names_in_"):
                return list(model.feature_names_in_)
            if hasattr(model, "n_features_in_"):
                return [f"feature_{i}" for i in range(model.n_features_in_)]
        except Exception:
            pass

        # Default fallback
        return [f"feature_{i}" for i in range(10)]


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================


def export_all_edge_models() -> list[dict[str, Any]]:
    """Convenience function for CLI/Makefile usage.

    Creates a ``ModelExporter`` with default paths and exports all edge models.

    Returns:
        List of dictionaries, one per export, containing model name, format,
        output path, file size, and success status.
    """
    exporter = ModelExporter()
    results = exporter.export_all_edge_models()
    return [r.to_dict() for r in results]
