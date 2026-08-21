from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AWS_ROOT = ROOT / 'AWS Deployment' / 'aether-aws'


@contextmanager
def aws_module_path():
    original = list(sys.path)
    for prefix in ('main', 'shared', 'config', 'scripts'):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name.startswith(f'{prefix}.'):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(AWS_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in ('main', 'shared', 'config', 'scripts'):
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name.startswith(f'{prefix}.'):
                    sys.modules.pop(name, None)


def test_aws_client_factory_uses_runtime_env(monkeypatch):
    with aws_module_path():
        monkeypatch.setenv('AETHER_STUB_AWS', '1')
        aws_client = importlib.import_module('shared.aws_client')
        importlib.reload(aws_client)

        factory = aws_client.AWSClientFactory()
        assert factory.is_stub is True

        monkeypatch.setenv('AETHER_STUB_AWS', '0')
        assert factory.is_stub is (not aws_client.BOTO_AVAILABLE)


def test_demo_runner_requires_explicit_stub_or_live_selection(monkeypatch):
    with aws_module_path():
        demo_main = importlib.import_module('main')
        importlib.reload(demo_main)

        monkeypatch.delenv('AETHER_STUB_AWS', raising=False)
        args = demo_main.parse_args([])
        assert demo_main.configure_stub_mode(args) is False
        assert os.environ.get('AETHER_STUB_AWS') is None

        args = demo_main.parse_args(['--stub-aws'])
        assert demo_main.configure_stub_mode(args) is True
        assert os.environ['AETHER_STUB_AWS'] == '1'

        args = demo_main.parse_args(['--live-aws'])
        assert demo_main.configure_stub_mode(args) is False
        assert os.environ['AETHER_STUB_AWS'] == '0'


def test_aws_module_path_does_not_leak_aws_scripts_package():
    """The AWS demo ``main`` imports ``scripts.capacity.*`` etc., caching the
    AWS ``scripts`` package in ``sys.modules``. The context must evict it on
    exit, or a later test doing ``from scripts import <root_validator>`` in the
    same worker resolves to the AWS package and ImportErrors — a race observed
    under pytest-xdist ``-n auto`` (PR #519 follow-up)."""
    with aws_module_path():
        importlib.import_module('main')  # pulls in AWS scripts.capacity.*
    assert 'scripts' not in sys.modules, 'AWS scripts package leaked into sys.modules'
    from scripts import validate_signal_use_matrix as root_validator
    assert hasattr(root_validator, 'main')
