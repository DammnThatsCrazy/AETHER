from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("httpx", reason="httpx required (pip install -e '.[backend]')")

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / 'Agent Layer'


@contextmanager
def agent_module_path():
    original = list(sys.path)
    prefixes = ('config', 'models', 'workers', 'web_crawler')

    def _purge():
        for prefix in prefixes:
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f'{prefix}.'):
                    sys.modules.pop(name, None)

    _purge()
    sys.path.insert(0, str(AGENT_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        # Symmetric teardown: the ``Agent Layer`` root shares bare top-level
        # package names (``config``/``models``/``workers``) with the backend
        # and repo root. Leaving Agent Layer's copies cached in ``sys.modules``
        # poisons any backend test that later runs in the same pytest-xdist
        # worker. Purge on exit so the next import resolves against the caller's
        # own ``sys.path``.
        _purge()


def test_top_level_web_crawler_wraps_canonical_worker():
    with agent_module_path():
        wrapper = importlib.import_module('web_crawler')
        canonical = importlib.import_module('workers.discovery.web_crawler')
        assert wrapper.WebCrawlerWorker is canonical.WebCrawlerWorker
