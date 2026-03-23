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
    for prefix in ('config', 'models', 'workers', 'web_crawler'):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f'{prefix}.'):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(AGENT_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


def test_top_level_web_crawler_wraps_canonical_worker():
    with agent_module_path():
        wrapper = importlib.import_module('web_crawler')
        canonical = importlib.import_module('workers.discovery.web_crawler')
        assert wrapper.WebCrawlerWorker is canonical.WebCrawlerWorker
