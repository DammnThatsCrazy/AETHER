"""Guard against test stubs shadowing genuinely installed dependencies.

`tests/agentic_x402/conftest.py` stubs external packages so its imports resolve
in a sandbox without them. Conftest bodies run at collection time and
``sys.modules`` is process-global, so a stub installed there outlives the
package that declared it.

That combination produced a real, long-lived defect: the stub loop registered a
fake ``starlette.testclient`` exposing ``TestClient = object`` whenever that
submodule had not yet been imported — true even when starlette itself was
installed. Every suite collected afterwards that constructed ``TestClient(app)``
then failed with ``TypeError: object() takes no arguments``. Each affected file
passed in isolation and failed only in a whole-tree run, so it survived
undetected for as long as no gate executed the backend tree.

These tests assert the invariant directly: a stub may stand in for an absent
dependency, never on top of a present one.
"""

from __future__ import annotations

import importlib
import sys

import pytest

# Import name -> distribution name for the packages whose real implementations
# the backend suites depend on. If the distribution is installed, nothing in the
# test tree may replace its module with a stand-in.
REAL_DEPENDENCIES: dict[str, str] = {
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "starlette": "starlette",
    "starlette.testclient": "starlette",
    "jwt": "PyJWT",
    "cryptography": "cryptography",
    "asyncpg": "asyncpg",
}


def _installed(module: str) -> bool:
    """Report whether the distribution providing ``module`` is installed.

    This deliberately consults installed-distribution metadata rather than
    ``importlib.util.find_spec``. ``find_spec`` short-circuits on ``sys.modules``,
    so once a conftest has injected a hand-built ``types.ModuleType`` — which has
    no ``__spec__`` — ``find_spec`` returns ``None`` and the package looks absent.
    A guard built on it therefore *skips* in exactly the situation it exists to
    catch, reporting green while the corruption it hunts is present. Distribution
    metadata is unaffected by anything a test does to ``sys.modules``.
    """
    from importlib.metadata import PackageNotFoundError, distribution

    dist_name = REAL_DEPENDENCIES.get(module, module)
    try:
        distribution(dist_name)
    except PackageNotFoundError:
        return False
    return True


@pytest.mark.parametrize("module_name", sorted(REAL_DEPENDENCIES))
def test_installed_dependency_is_not_shadowed_by_a_stub(module_name: str) -> None:
    """An installed package must resolve to its real file-backed module."""
    if not _installed(module_name):
        pytest.skip(f"{module_name} is not installed in this environment")

    module = importlib.import_module(module_name)
    origin = getattr(module, "__file__", None)

    assert origin is not None, (
        f"{module_name} is installed but resolves to a module with no __file__, "
        "which means a test stub replaced it in sys.modules. A stub may substitute "
        "for an absent dependency, never shadow an installed one."
    )
    assert "site-packages" in origin or "dist-packages" in origin, (
        f"{module_name} resolves to {origin}, not an installed distribution."
    )


def test_starlette_testclient_is_constructible() -> None:
    """``TestClient`` must be a real class, not the ``object`` sentinel.

    This is the exact failure the stub caused: ``TestClient = object`` makes
    ``TestClient(app)`` raise ``TypeError: object() takes no arguments`` at
    module import, turning a collection error into a whole-suite outage.
    """
    if not _installed("starlette.testclient"):
        pytest.skip("starlette is not installed in this environment")

    from starlette.testclient import TestClient

    assert TestClient is not object, (
        "starlette.testclient.TestClient is the bare object sentinel — a test "
        "stub has shadowed the real starlette. Constructing it raises "
        "'TypeError: object() takes no arguments' in every suite collected after "
        "the stub was installed."
    )
    assert isinstance(TestClient, type)
    assert hasattr(TestClient, "get"), "TestClient is a class but not the HTTP client"


def test_no_stubbed_module_leaked_into_this_session() -> None:
    """No module in the current session is a stub standing over an installed package."""
    leaked: list[str] = []
    for name in REAL_DEPENDENCIES:
        if not _installed(name):
            continue
        loaded = sys.modules.get(name)
        if loaded is not None and getattr(loaded, "__file__", None) is None:
            leaked.append(name)

    assert not leaked, (
        f"stub modules leaked over installed packages: {leaked}. A conftest "
        "installed a stand-in during collection and never removed it."
    )
