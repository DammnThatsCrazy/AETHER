"""
Aether ML -- Batch Prediction Service

Offline and online batch scoring for large datasets.  Supports chunked
processing with configurable parallelism, multiple I/O formats (Parquet,
CSV, JSON Lines), and optional S3 integration.

Deployed as: SageMaker Processing Job, ECS Fargate task, or called
directly from the ``/v1/predict/batch`` API endpoint for moderate payloads.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("aether.serving.batch")


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class BatchConfig:
    """Tunable parameters for a batch prediction job."""

    model_name: str
    input_path: str = ""                   # S3 or local path to input data
    output_path: str = ""                  # S3 or local path for results
    input_format: str = "parquet"          # parquet | csv | json
    output_format: str = "parquet"         # parquet | csv | json
    chunk_size: int = 10_000               # rows per chunk for memory control
    max_workers: int = 4                   # parallel worker threads
    include_features: bool = False         # echo input features in output
    include_metadata: bool = True          # append model version / timestamp
    timestamp_column: Optional[str] = None # column for incremental filtering
    since_timestamp: Optional[str] = None  # ISO-8601 lower bound for incremental


@dataclass
class BatchJobResult:
    """Summary produced at the end of a batch job."""

    job_id: str
    model_name: str
    model_version: str
    input_rows: int
    output_rows: int
    failed_rows: int
    duration_seconds: float
    output_path: str
    started_at: str
    completed_at: str
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "input_rows": self.input_rows,
            "output_rows": self.output_rows,
            "failed_rows": self.failed_rows,
            "duration_s": round(self.duration_seconds, 1),
            "rows_per_second": round(
                self.output_rows / max(self.duration_seconds, 0.01)
            ),
            "output_path": self.output_path,
            "metrics": self.metrics,
        }


# =============================================================================
# DATA LOADERS
# =============================================================================


class BatchDataLoader:
    """Load data in chunks for memory-efficient batch processing."""

    @staticmethod
    def load_chunks(
        path: str, fmt: str, chunk_size: int
    ) -> list[pd.DataFrame]:
        """Read a local file and split it into equally-sized chunks.

        Parameters
        ----------
        path:
            Local filesystem path.
        fmt:
            ``"parquet"``, ``"csv"``, or ``"json"`` (JSON Lines).
        chunk_size:
            Maximum rows per chunk.

        Returns
        -------
        A list of DataFrames, each containing at most ``chunk_size`` rows.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        if fmt == "parquet":
            df = pd.read_parquet(p)
            return [
                df.iloc[i : i + chunk_size]
                for i in range(0, len(df), chunk_size)
            ]
        elif fmt == "csv":
            chunks: list[pd.DataFrame] = []
            for chunk in pd.read_csv(p, chunksize=chunk_size):
                chunks.append(chunk)
            return chunks
        elif fmt == "json":
            df = pd.read_json(p, lines=True)
            return [
                df.iloc[i : i + chunk_size]
                for i in range(0, len(df), chunk_size)
            ]
        else:
            raise ValueError(f"Unsupported input format: {fmt}")

    @staticmethod
    def load_from_s3(s3_path: str, fmt: str) -> pd.DataFrame:
        """Download and parse a single object from S3."""
        import io

        import boto3

        parts = s3_path.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read()

        if fmt == "parquet":
            return pd.read_parquet(io.BytesIO(body))
        elif fmt == "csv":
            return pd.read_csv(io.BytesIO(body))
        elif fmt == "json":
            return pd.read_json(io.BytesIO(body), lines=True)
        else:
            raise ValueError(f"Unsupported format: {fmt}")


# =============================================================================
# BATCH PREDICTOR
# =============================================================================


class BatchPredictor:
    """
    Execute batch predictions on large datasets.

    Supports two usage patterns:

    1. **API-driven** (moderate payloads): instantiate with a ``ModelServer``,
       call ``predict_batch()`` or ``predict_dataframe()`` directly.
    2. **Job-driven** (large datasets): configure via ``BatchConfig``, load a
       model via ``load_model()``, then call ``run()`` to read from disk /
       S3, score, and write results.

    Both paths use chunked processing and optional thread-pool parallelism
    to keep memory bounded and latency low.
    """

    def __init__(
        self,
        model_server: Any = None,
        config: Optional[BatchConfig] = None,
        max_workers: int = 4,
        batch_size: int = 10_000,
    ) -> None:
        self.model_server = model_server
        self.config = config
        self.max_workers = max_workers
        self.batch_size = batch_size
        self._model: Any = None

    # --------------------------------------------------------------------- #
    # API-driven helpers (used by the /v1/predict/batch endpoint)
    # --------------------------------------------------------------------- #

    def predict_batch(
        self, model_name: str, instances: list[dict[str, Any]]
    ) -> list[Any]:
        """Run batch prediction on a list of feature dicts.

        Chunks the instances, scores each chunk (optionally in parallel),
        and returns a flat list of predictions in the original order.
        """
        if not instances:
            return []

        chunks = self._chunk_list(instances, self.batch_size)

        if len(chunks) == 1:
            return self._predict_chunk(model_name, chunks[0])

        # Parallel scoring across chunks.
        results: list[tuple[int, list[Any]]] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._predict_chunk, model_name, chunk): idx
                for idx, chunk in enumerate(chunks)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    preds = future.result()
                    results.append((idx, preds))
                except Exception as exc:
                    logger.error("Chunk %d failed: %s", idx, exc)
                    # Fill failed chunk with None so output length is preserved.
                    results.append(
                        (idx, [None] * len(chunks[idx]))
                    )

        # Re-order chunks by their original index.
        results.sort(key=lambda r: r[0])
        return [pred for _, chunk_preds in results for pred in chunk_preds]

    def predict_dataframe(
        self, model_name: str, df: pd.DataFrame
    ) -> pd.Series:
        """Run prediction on a full DataFrame and return a Series of results.

        This is a convenience wrapper that converts the DataFrame to a list
        of dicts, runs ``predict_batch()``, and aligns the output index with
        the input DataFrame.
        """
        instances = df.to_dict(orient="records")
        predictions = self.predict_batch(model_name, instances)
        return pd.Series(predictions, index=df.index, name="prediction")

    # --------------------------------------------------------------------- #
    # Job-driven execution (offline batch scoring)
    # --------------------------------------------------------------------- #

    def load_model(self, model: Any) -> None:
        """Register a pre-loaded model for job-based batch scoring."""
        self._model = model
        logger.info(
            "Model loaded for batch: %s v%s",
            getattr(model, "model_type", "unknown"),
            getattr(model, "version", "0.0.0"),
        )

    def run(self) -> BatchJobResult:
        """Execute a full batch prediction job as defined by ``self.config``.

        Reads input from local disk or S3, scores in chunks, writes output,
        and returns a summary ``BatchJobResult``.
        """
        if self._model is None:
            raise RuntimeError("No model loaded. Call load_model() first.")
        if self.config is None:
            raise RuntimeError("No BatchConfig provided.")

        job_id = f"batch-{self.config.model_name}-{int(time.time())}"
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.time()

        logger.info("Starting batch job %s: %s", job_id, self.config.input_path)

        # Load data ---------------------------------------------------------
        if self.config.input_path.startswith("s3://"):
            full_df = BatchDataLoader.load_from_s3(
                self.config.input_path, self.config.input_format
            )
            chunks = [
                full_df.iloc[i : i + self.config.chunk_size]
                for i in range(0, len(full_df), self.config.chunk_size)
            ]
        else:
            chunks = BatchDataLoader.load_chunks(
                self.config.input_path,
                self.config.input_format,
                self.config.chunk_size,
            )

        input_rows = sum(len(c) for c in chunks)
        logger.info("Loaded %d rows in %d chunks", input_rows, len(chunks))

        # Incremental filter ------------------------------------------------
        if self.config.since_timestamp and self.config.timestamp_column:
            filtered: list[pd.DataFrame] = []
            for chunk in chunks:
                if self.config.timestamp_column in chunk.columns:
                    mask = chunk[self.config.timestamp_column] > self.config.since_timestamp
                    subset = chunk[mask]
                    if len(subset) > 0:
                        filtered.append(subset)
            chunks = filtered
            logger.info(
                "After incremental filter: %d rows",
                sum(len(c) for c in chunks),
            )

        # Score -------------------------------------------------------------
        all_predictions: list[pd.DataFrame] = []
        failed_rows = 0

        for idx, chunk in enumerate(chunks):
            try:
                preds = self._predict_chunk_df(chunk, idx)
                all_predictions.append(preds)
            except Exception as exc:
                logger.error("Chunk %d failed: %s", idx, exc)
                failed_rows += len(chunk)

        if not all_predictions:
            logger.error("No predictions generated for job %s", job_id)
            return BatchJobResult(
                job_id=job_id,
                model_name=self.config.model_name,
                model_version=getattr(self._model, "version", "0.0.0"),
                input_rows=input_rows,
                output_rows=0,
                failed_rows=failed_rows,
                duration_seconds=time.time() - t0,
                output_path="",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        output_df = pd.concat(all_predictions, ignore_index=True)

        # Save --------------------------------------------------------------
        self._save_output(output_df, job_id)

        duration = time.time() - t0
        completed_at = datetime.now(timezone.utc).isoformat()
        metrics = self._compute_summary_metrics(output_df)

        result = BatchJobResult(
            job_id=job_id,
            model_name=self.config.model_name,
            model_version=getattr(self._model, "version", "0.0.0"),
            input_rows=input_rows,
            output_rows=len(output_df),
            failed_rows=failed_rows,
            duration_seconds=duration,
            output_path=self.config.output_path,
            started_at=started_at,
            completed_at=completed_at,
            metrics=metrics,
        )

        logger.info("Batch job complete: %s", result.to_dict())
        return result

    # --------------------------------------------------------------------- #
    # Private helpers
    # --------------------------------------------------------------------- #

    def _predict_chunk(
        self, model_name: str, chunk: list[dict[str, Any]]
    ) -> list[Any]:
        """Score a single chunk via the ModelServer (API-driven path)."""
        if self.model_server is None:
            raise RuntimeError("model_server is required for predict_chunk")

        model = self.model_server.get_model(model_name)
        df = pd.DataFrame(chunk)
        raw = model.predict(df)

        results: list[Any] = []
        for pred in raw:
            if isinstance(pred, (np.integer,)):
                results.append(int(pred))
            elif isinstance(pred, (np.floating,)):
                results.append(float(pred))
            elif isinstance(pred, np.ndarray):
                results.append(pred.tolist())
            else:
                results.append(pred)
        return results

    def _predict_chunk_df(
        self, chunk: pd.DataFrame, chunk_idx: int
    ) -> pd.DataFrame:
        """Score a single DataFrame chunk (job-driven path).

        Returns a DataFrame with entity-ID columns, prediction columns,
        optional probabilities, and metadata.
        """
        predictions = self._model.predict(chunk)

        result = pd.DataFrame()

        # Preserve entity ID columns from input.
        id_columns = [
            "session_id",
            "identity_id",
            "wallet_address",
            "user_id",
            "anonymous_id",
        ]
        for col in id_columns:
            if col in chunk.columns:
                result[col] = chunk[col].values

        # Add predictions.
        if isinstance(predictions, dict):
            for key, values in predictions.items():
                result[f"pred_{key}"] = values
        elif hasattr(predictions, "ndim") and predictions.ndim == 2:
            for i in range(predictions.shape[1]):
                result[f"pred_class_{i}"] = predictions[:, i]
        else:
            result["prediction"] = (
                predictions if hasattr(predictions, "__len__") else [predictions]
            )

        # Add class probabilities if available.
        if hasattr(self._model, "predict_proba"):
            try:
                probas = self._model.predict_proba(chunk)
                if hasattr(probas, "ndim") and probas.ndim == 2:
                    for i in range(probas.shape[1]):
                        result[f"proba_class_{i}"] = probas[:, i]
                else:
                    result["probability"] = probas
            except Exception:
                pass  # Model may not support predict_proba for all inputs.

        # Add enrichment columns (e.g. top churn factors).
        if hasattr(self._model, "predict_with_factors"):
            try:
                enriched = self._model.predict_with_factors(chunk)
                for col in enriched.columns:
                    if col not in result.columns:
                        result[col] = enriched[col].values
            except Exception:
                pass

        # Echo input features if requested.
        if self.config is not None and self.config.include_features:
            for col in chunk.columns:
                if col not in result.columns:
                    result[f"feat_{col}"] = chunk[col].values

        # Metadata columns.
        if self.config is not None and self.config.include_metadata:
            result["model_name"] = self.config.model_name
            result["model_version"] = getattr(self._model, "version", "0.0.0")
            result["scored_at"] = datetime.now(timezone.utc).isoformat()

        return result

    def _save_output(self, df: pd.DataFrame, job_id: str) -> None:
        """Write prediction results to disk or S3."""
        if self.config is None:
            return

        output_path = self.config.output_path
        if output_path.startswith("s3://"):
            self._save_to_s3(df, output_path, job_id)
        else:
            p = Path(output_path)
            p.mkdir(parents=True, exist_ok=True)
            if self.config.output_format == "parquet":
                df.to_parquet(p / f"{job_id}.parquet", index=False)
            elif self.config.output_format == "csv":
                df.to_csv(p / f"{job_id}.csv", index=False)
            elif self.config.output_format == "json":
                df.to_json(
                    p / f"{job_id}.jsonl", orient="records", lines=True
                )

    def _save_to_s3(self, df: pd.DataFrame, s3_path: str, job_id: str) -> None:
        """Upload prediction results to S3."""
        import io

        import boto3

        parts = s3_path.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""

        buffer = io.BytesIO()
        fmt = self.config.output_format if self.config else "parquet"
        if fmt == "parquet":
            df.to_parquet(buffer, index=False)
            key = f"{prefix}/{job_id}.parquet"
        else:
            df.to_csv(buffer, index=False)
            key = f"{prefix}/{job_id}.csv"

        buffer.seek(0)
        s3 = boto3.client("s3")
        s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())

    def _compute_summary_metrics(self, df: pd.DataFrame) -> dict[str, float]:
        """Derive summary statistics from prediction output."""
        metrics: dict[str, float] = {}

        if "prediction" in df.columns:
            series = df["prediction"]
            if pd.api.types.is_numeric_dtype(series):
                metrics["pred_mean"] = float(series.mean())
                metrics["pred_std"] = float(series.std())
                metrics["pred_median"] = float(series.median())
                metrics["pred_p95"] = float(series.quantile(0.95))

        if "probability" in df.columns:
            prob = df["probability"]
            metrics["proba_mean"] = float(prob.mean())
            metrics["high_risk_count"] = int((prob > 0.7).sum())
            metrics["high_risk_pct"] = round(float((prob > 0.7).mean() * 100), 2)

        if "churn_probability" in df.columns:
            metrics["churn_high_risk"] = int(
                (df["churn_probability"] > 0.6).sum()
            )

        return metrics

    @staticmethod
    def _chunk_list(
        items: list[dict[str, Any]], size: int
    ) -> list[list[dict[str, Any]]]:
        """Split a flat list into sub-lists of at most ``size`` elements."""
        return [items[i : i + size] for i in range(0, len(items), size)]
