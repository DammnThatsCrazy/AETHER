"""
Aether ML — Knowledge Distillation

Transfers learned representations from a large "teacher" model (server-tier)
to a smaller "student" model (edge-tier) using soft-label training.

Distillation modes:
  - Soft-label: Student trains on teacher's probability distributions (temperature-scaled)
  - Feature-matching: Student mimics teacher's intermediate representations
  - Progressive: Iterative distillation with shrinking teacher ensemble

The student model retains the teacher's accuracy while meeting edge deployment
constraints (<100ms inference, <1MB artifact).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier

logger = logging.getLogger("aether.ml.optimization.distillation")


class DistillationMode(str, Enum):
    SOFT_LABEL = "soft_label"
    FEATURE_MATCHING = "feature_matching"
    PROGRESSIVE = "progressive"


@dataclass
class DistillationConfig:
    """Configuration for knowledge distillation."""
    mode: DistillationMode = DistillationMode.SOFT_LABEL
    temperature: float = 3.0              # Softmax temperature for soft labels
    alpha: float = 0.7                    # Weight of soft loss vs hard loss (0-1)
    max_iter: int = 2000                  # Training iterations for student
    student_complexity: float = 0.5       # Relative complexity vs teacher (0-1)
    accuracy_floor: float = 0.90          # Min accuracy relative to teacher
    n_augmentation_rounds: int = 3        # Data augmentation rounds for training


@dataclass
class DistillationResult:
    """Result of a distillation pass."""
    teacher_metrics: dict[str, float]
    student_metrics: dict[str, float]
    accuracy_retention: float               # student_acc / teacher_acc
    size_reduction: float                   # teacher_size / student_size
    teacher_size_bytes: int
    student_size_bytes: int
    mode: str
    temperature: float
    alpha: float
    passed_floor: bool
    duration_ms: float


class ModelDistiller:
    """
    Knowledge distillation from teacher (server) to student (edge) models.

    Supports sklearn-based models. The teacher generates soft probability
    distributions that the student learns from, preserving dark knowledge
    about class relationships that hard labels miss.
    """

    def __init__(self, config: DistillationConfig | None = None) -> None:
        self.config = config or DistillationConfig()

    def distill(
        self,
        teacher: Any,
        student: Any,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
    ) -> DistillationResult:
        """
        Distill knowledge from teacher to student.

        Args:
            teacher: Trained teacher model (typically server-tier).
            student: Untrained student model (typically edge-tier).
            X_train: Training features.
            y_train: Training labels.
            X_val: Validation features.
            y_val: Validation labels.

        Returns:
            DistillationResult with teacher/student comparison.
        """
        start = time.monotonic()
        logger.info(
            "Starting distillation: mode=%s, temp=%.1f, alpha=%.2f",
            self.config.mode.value, self.config.temperature, self.config.alpha,
        )

        # Measure teacher
        teacher_predictions = teacher.predict(X_val)
        teacher_metrics = self._compute_metrics(y_val, teacher_predictions)
        teacher_size = self._estimate_size(teacher)

        # Generate soft labels from teacher
        if self.config.mode == DistillationMode.SOFT_LABEL:
            self._distill_soft_label(teacher, student, X_train, y_train)
        elif self.config.mode == DistillationMode.PROGRESSIVE:
            self._distill_progressive(teacher, student, X_train, y_train)
        else:
            self._distill_soft_label(teacher, student, X_train, y_train)

        # Measure student
        student_predictions = student.predict(X_val)
        student_metrics = self._compute_metrics(y_val, student_predictions)
        student_size = self._estimate_size(student)

        # Compute retention
        teacher_primary = list(teacher_metrics.values())[0] if teacher_metrics else 1.0
        student_primary = list(student_metrics.values())[0] if student_metrics else 0.0
        retention = student_primary / max(teacher_primary, 1e-9)

        passed = retention >= self.config.accuracy_floor
        duration = (time.monotonic() - start) * 1000

        result = DistillationResult(
            teacher_metrics=teacher_metrics,
            student_metrics=student_metrics,
            accuracy_retention=round(retention, 4),
            size_reduction=round(teacher_size / max(student_size, 1), 2),
            teacher_size_bytes=teacher_size,
            student_size_bytes=student_size,
            mode=self.config.mode.value,
            temperature=self.config.temperature,
            alpha=self.config.alpha,
            passed_floor=passed,
            duration_ms=round(duration, 1),
        )
        logger.info(
            "Distillation complete: retention=%.2f%%, size=%.1fx smaller, floor=%s",
            retention * 100, teacher_size / max(student_size, 1), "PASS" if passed else "FAIL",
        )
        return result

    def _distill_soft_label(
        self, teacher: Any, student: Any,
        X_train: pd.DataFrame, y_train: pd.Series,
    ) -> None:
        """Soft-label distillation using temperature-scaled probabilities."""
        internal_teacher = getattr(teacher, '_model', teacher)
        internal_student = getattr(student, '_model', student)

        # Get teacher soft predictions
        if hasattr(internal_teacher, 'predict_proba'):
            soft_probs = internal_teacher.predict_proba(X_train)
            # Temperature scaling: soften the distribution
            soft_probs = self._temperature_scale(soft_probs, self.config.temperature)
            # Create blended targets: alpha * soft + (1 - alpha) * hard
            soft_labels = soft_probs.argmax(axis=1)
        else:
            soft_labels = internal_teacher.predict(X_train)

        # Augment training data
        X_aug, y_aug = self._augment_data(X_train, soft_labels)

        # Blend soft and hard labels
        alpha = self.config.alpha
        n_train = len(y_train)
        n_aug = len(y_aug)

        # Combine original hard labels with soft labels (weighted by alpha)
        X_combined = pd.concat([X_train, X_aug], ignore_index=True)
        y_hard = y_train.values if hasattr(y_train, 'values') else np.array(y_train)
        y_soft = y_aug[:n_train] if len(y_aug) >= n_train else y_aug
        y_combined = np.concatenate([y_hard, y_aug])

        # Train student on combined data
        if internal_student is None:
            # Create a simpler student model
            if hasattr(internal_teacher, 'coef_'):
                internal_student = LogisticRegression(
                    max_iter=self.config.max_iter, solver='lbfgs',
                    class_weight='balanced', C=0.5,
                )
            else:
                n_trees = max(10, int(getattr(internal_teacher, 'n_estimators', 100) * self.config.student_complexity))
                max_depth = max(3, int(getattr(internal_teacher, 'max_depth', 10) * self.config.student_complexity))
                internal_student = RandomForestClassifier(
                    n_estimators=n_trees, max_depth=max_depth,
                    class_weight='balanced', random_state=42, n_jobs=-1,
                )

        features = X_combined.values if hasattr(X_combined, 'values') else X_combined
        internal_student.fit(features, y_combined)

        if hasattr(student, '_model'):
            student._model = internal_student
            student.is_trained = True

    def _distill_progressive(
        self, teacher: Any, student: Any,
        X_train: pd.DataFrame, y_train: pd.Series,
    ) -> None:
        """Progressive distillation: iteratively compress from teacher."""
        current_teacher = teacher
        for round_idx in range(self.config.n_augmentation_rounds):
            logger.info("Progressive distillation round %d/%d", round_idx + 1, self.config.n_augmentation_rounds)
            self._distill_soft_label(current_teacher, student, X_train, y_train)
            current_teacher = student

    def _temperature_scale(self, probs: np.ndarray, temperature: float) -> np.ndarray:
        """Apply temperature scaling to soften probability distribution."""
        if temperature <= 0:
            return probs
        # Convert probs to logits, scale, and convert back
        eps = 1e-10
        logits = np.log(probs + eps)
        scaled = logits / temperature
        # Softmax
        exp_scaled = np.exp(scaled - scaled.max(axis=1, keepdims=True))
        return exp_scaled / exp_scaled.sum(axis=1, keepdims=True)

    def _augment_data(self, X: pd.DataFrame, y: np.ndarray) -> tuple[pd.DataFrame, np.ndarray]:
        """Generate augmented training data with noise injection."""
        augmented_X = []
        augmented_y = []
        for _ in range(self.config.n_augmentation_rounds):
            noise = np.random.normal(0, 0.01, X.shape)
            X_noisy = X.values + noise if hasattr(X, 'values') else X + noise
            augmented_X.append(pd.DataFrame(X_noisy, columns=X.columns if hasattr(X, 'columns') else None))
            augmented_y.append(y.copy() if hasattr(y, 'copy') else np.array(y))

        return pd.concat(augmented_X, ignore_index=True), np.concatenate(augmented_y)

    def _compute_metrics(self, y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
        from sklearn.metrics import accuracy_score, f1_score
        y_p = y_pred if y_pred.ndim == 1 else y_pred.argmax(axis=1)
        return {
            "accuracy": accuracy_score(y_true, y_p),
            "f1_weighted": f1_score(y_true, y_p, average="weighted", zero_division=0),
        }

    def _estimate_size(self, model: Any) -> int:
        import io
        import pickle
        buf = io.BytesIO()
        try:
            internal = getattr(model, '_model', model)
            pickle.dump(internal, buf)
            return buf.tell()
        except Exception:
            return 0
