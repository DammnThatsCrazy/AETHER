"""
Aether Agent Layer — Worker Registry
Auto-discovers and registers all worker classes from the discovery/
and enrichment/ sub-packages.

Usage:
    from workers.registry import discover_workers
    workers = discover_workers(guardrails)
    for w in workers:
        controller.register_worker(w)
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import TYPE_CHECKING

from config.settings import WorkerType

from workers.base import BaseWorker

if TYPE_CHECKING:
    from guardrails.guardrails import Guardrails

logger = logging.getLogger("aether.worker.registry")

# Sub-packages that contain worker modules
_WORKER_PACKAGES = (
    "workers.discovery",
    "workers.enrichment",
)


def _iter_worker_classes() -> list[type[BaseWorker]]:
    """
    Walk _WORKER_PACKAGES, import every module, and collect concrete
    BaseWorker subclasses.
    """
    classes: list[type[BaseWorker]] = []

    for pkg_name in _WORKER_PACKAGES:
        try:
            pkg = importlib.import_module(pkg_name)
        except ImportError as exc:
            logger.warning(f"Could not import package {pkg_name}: {exc}")
            continue

        pkg_path = getattr(pkg, "__path__", None)
        if pkg_path is None:
            continue

        for importer, module_name, is_pkg in pkgutil.iter_modules(pkg_path):
            full_name = f"{pkg_name}.{module_name}"
            try:
                mod = importlib.import_module(full_name)
            except ImportError as exc:
                logger.warning(f"Could not import module {full_name}: {exc}")
                continue

            for _name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, BaseWorker)
                    and obj is not BaseWorker
                    and not inspect.isabstract(obj)
                    and hasattr(obj, "worker_type")
                ):
                    classes.append(obj)

    return classes


def discover_workers(guardrails: Guardrails) -> list[BaseWorker]:
    """
    Discover all concrete worker classes and instantiate them with the
    shared Guardrails instance.

    Returns a list of ready-to-register worker instances (one per WorkerType).
    """
    seen: set[WorkerType] = set()
    workers: list[BaseWorker] = []

    for cls in _iter_worker_classes():
        wt = cls.worker_type
        if wt in seen:
            logger.warning(
                f"Duplicate worker for {wt.value}: {cls.__name__} "
                f"(already registered)"
            )
            continue
        seen.add(wt)
        workers.append(cls(guardrails))
        logger.info(f"Discovered worker: {cls.__name__} → {wt.value}")

    # Report any WorkerTypes without implementations
    missing = set(WorkerType) - seen
    if missing:
        logger.warning(
            f"No workers found for: {[m.value for m in missing]}"
        )

    return workers
