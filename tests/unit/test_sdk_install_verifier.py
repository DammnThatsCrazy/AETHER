"""The install verifier — proving a pasted snippet actually came up.

An install that delivers nothing looks exactly like an install that was never
pasted: both are silence. The verifier exists to tell them apart, so the
properties worth testing are the ones that keep that answer honest:

  * the projection reads the loader's own signals and nothing else — an
    ordinary event must never be mistaken for one;
  * a failure is visible, and a *fixed* failure stops being visible, because a
    site reported broken forever is a site nobody looks at;
  * a site with no signals says so rather than defaulting to a healthy state;
  * the signals reach the record through the real ingestion spine, after
    durability, without the projection being able to fail a batch;
  * site installs do not pollute fleet health — they have no heartbeat by
    design, so counting them would call every correct install a silent SDK.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "services" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

from repositories.sdk_repos import (  # noqa: E402
    SITE_INSTALL_RECORD_TYPE,
    SDKInstallationRepository,
)
from services.sdk_distribution.install_verifier import (  # noqa: E402
    SIGNAL_INITIALIZED,
    SIGNAL_LOADED,
    SIGNAL_FAILED,
    STATE_AWAITING,
    STATE_FAILED,
    STATE_LIVE,
    STATE_LOADED,
    describe_site_install,
    install_signal,
    record_install_signals,
    merge_site_install,
    schedule_install_projection,
)
from services.sdk_distribution.versions import (  # noqa: E402
    DRIFT_AHEAD,
    DRIFT_BEHIND,
    DRIFT_CURRENT,
    DRIFT_UNKNOWN,
)

SITE = "site_install_verifier"
LOADER_VERSION = "0.1.0-alpha.0"


def _event(signal: str, **properties) -> dict:
    """An accepted, normalized install signal as ingestion stores it."""
    props = {"siteId": SITE, "loaderVersion": LOADER_VERSION, "installMode": "cdn_auto"}
    props.update(properties)
    return {
        "event_id": f"evt-{signal}",
        "event_type": signal,
        "properties": props,
        "context": {"library": {"name": "@aether/sdk", "version": LOADER_VERSION}},
        "timestamp": "2026-09-15T10:00:00+00:00",
        "received_at": "2026-09-15T10:00:00+00:00",
    }


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── What counts as an install signal ─────────────────────────────────────────

def test_ordinary_events_are_not_install_signals():
    """This runs on every accepted event in the platform, so a false positive
    would attribute unrelated traffic to a site's install handshake."""
    assert install_signal(_event("order_completed")) is None
    assert install_signal({"event_type": "page_view", "properties": {"siteId": SITE}}) is None


def test_a_signal_with_no_site_is_refused_rather_than_guessed():
    """Guessing the tenant's only site would misattribute the signal in exactly
    the case the operator is debugging: a snippet pasted without data-site."""
    assert install_signal({
        "event_type": SIGNAL_LOADED,
        "properties": {"loaderVersion": LOADER_VERSION},
    }) is None


def test_the_signal_carries_what_the_loader_reported():
    fact = install_signal(_event(SIGNAL_FAILED, reason="no apiKey", warnings=["deprecated attr"]))
    assert fact["signal"] == SIGNAL_FAILED
    assert fact["site_id"] == SITE
    assert fact["loader_version"] == LOADER_VERSION
    assert fact["reason"] == "no apiKey"
    assert fact["warnings"] == ["deprecated attr"]


def test_loader_version_falls_back_to_the_library_block():
    """The loader stamps its version in both places; a signal that carries only
    one of them must still be attributable to a version."""
    event = _event(SIGNAL_LOADED)
    event["properties"].pop("loaderVersion")
    assert install_signal(event)["loader_version"] == LOADER_VERSION


# ── The record a site's signals build up ─────────────────────────────────────

def test_a_successful_install_reaches_live():
    record = merge_site_install(
        None, [install_signal(_event(SIGNAL_LOADED)), install_signal(_event(SIGNAL_INITIALIZED))], "t1"
    )
    assert record["status"] == "live"
    assert record["record_type"] == SITE_INSTALL_RECORD_TYPE
    assert record["installation_id"] == SITE
    assert set(record["signals"]) == {SIGNAL_LOADED, SIGNAL_INITIALIZED}
    assert describe_site_install(record)["state"] == STATE_LIVE


def test_loaded_without_initialization_is_its_own_state():
    """The loader ran and the SDK did not come up. Reporting that as "live"
    would hide the one case where the snippet is working and the install is
    not, and reporting it as "failed" would claim a failure we never saw."""
    record = merge_site_install(None, [install_signal(_event(SIGNAL_LOADED))], "t1")
    assert describe_site_install(record)["state"] == STATE_LOADED


def test_a_failure_is_visible_and_carries_its_reason():
    record = merge_site_install(
        None, [install_signal(_event(SIGNAL_FAILED, reason="config invalid"))], "t1"
    )
    described = describe_site_install(record)
    assert described["state"] == STATE_FAILED
    assert described["reason"] == "config invalid"


def test_a_failure_that_was_fixed_stops_being_reported():
    """A site reported broken forever is a site nobody looks at, so a later
    success has to clear the failure — while the history stays for diagnosis."""
    failed = merge_site_install(
        None, [install_signal(_event(SIGNAL_FAILED, reason="config invalid"))], "t1"
    )
    fixed = merge_site_install(failed, [install_signal(_event(SIGNAL_INITIALIZED))], "t1")

    described = describe_site_install(fixed)
    assert described["state"] == STATE_LIVE
    assert described["reason"] is None
    assert described["warnings"] == []
    # The failure is not erased — it is history, and it is still countable.
    assert fixed["signals"][SIGNAL_FAILED]["count"] == 1


def test_a_later_failure_does_not_erase_what_the_load_reported():
    """`sdk_init_failed` carries no installMode or version. Blanking the fields
    captured from the successful load would lose which install path the site is
    on — the first thing needed to debug the failure."""
    loaded = merge_site_install(None, [install_signal(_event(SIGNAL_LOADED))], "t1")
    failed = merge_site_install(loaded, [install_signal(_event(SIGNAL_FAILED, reason="boom"))], "t1")

    assert failed["install_mode"] == "cdn_auto"
    assert failed["loader_version"] == LOADER_VERSION


def test_a_signal_for_a_site_the_request_did_not_authenticate_as_is_refused():
    """`properties.siteId` is written by the caller, so it cannot be the only
    thing deciding which site a signal belongs to.

    A publishable key ships in page HTML. Without this, a key copied off one
    customer's page could post a signal naming a *different* site of the same
    tenant and forge that site's install state — reporting a broken install as
    live, or a working one as failed. The request's declared site is validated
    against the credential's binding by the route policy before it gets here, so
    it is the trustworthy half of the pair.
    """
    other = _event(SIGNAL_LOADED, siteId="some_other_site")

    assert _run(record_install_signals("t1", [other], declared_site=SITE)) == 0
    assert _run(record_install_signals("t1", [other], declared_site="some_other_site")) == 1

    # No declared site means a tenant-wide credential (a secret key), which is
    # already authorised for every site the tenant owns.
    assert _run(record_install_signals("t1", [other])) == 1


def test_a_site_that_never_signalled_says_so():
    """The absence is the finding. Defaulting an uninstalled site to a healthy
    state would make the verifier agree with the silence it exists to explain."""
    described = describe_site_install(None)
    assert described["state"] == STATE_AWAITING
    assert described["last_signal"] is None
    assert described["signals_observed"] == []
    assert described["signals_missing"] == [SIGNAL_LOADED, SIGNAL_INITIALIZED, SIGNAL_FAILED]


# ── Version position ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "reported, expected",
    [
        (LOADER_VERSION, DRIFT_CURRENT),
        ("0.0.9", DRIFT_BEHIND),
        ("0.2.0", DRIFT_AHEAD),
        ("not-a-version", DRIFT_UNKNOWN),
    ],
)
def test_drift_status_is_relative_to_the_shipped_version(reported, expected):
    """`ahead` is its own status rather than folded into `current`: a client
    running a version this backend does not know is a cache serving something
    unexpected, which wants a different response than a healthy install."""
    record = merge_site_install(None, [install_signal(_event(SIGNAL_LOADED, loaderVersion=reported))], "t1")
    assert record["drift_status"] == expected
    assert record["desired_version"] == LOADER_VERSION


def test_a_signal_reporting_no_version_anywhere_is_unknown_not_current():
    """`unknown` must not collapse into `current`: a client that told us nothing
    about its version is not evidence that it is up to date."""
    event = _event(SIGNAL_LOADED)
    event["properties"].pop("loaderVersion")
    event["context"] = {"library": {"name": "@aether/sdk"}}
    record = merge_site_install(None, [install_signal(event)], "t1")
    assert record["drift_status"] == DRIFT_UNKNOWN
    assert record["compatibility_tier"] == "unclassified"


def test_the_shipped_loader_version_is_classified_not_unclassified():
    """The verifier reports a compatibility tier for every install. If the
    shipping version fell outside the band table, every install would read
    `unclassified` and the tier would be decoration."""
    record = merge_site_install(None, [install_signal(_event(SIGNAL_LOADED))], "t1")
    assert record["compatibility_tier"] == "supported"


# ── The ingestion seam ───────────────────────────────────────────────────────

def test_ingestion_projects_a_real_install_signal_after_durability():
    """Driven through the actual spine rather than the projection alone: the
    projection being correct is worth nothing if ingestion never calls it."""
    with _fresh() as env:
        producer = _FakeProducer()
        _ingest(env, [_sdk_event(env.batch, signal=SIGNAL_LOADED)], producer)

        # Read through this generation's repository: _fresh() re-imports the
        # backend, so a repository captured at module import would consult a
        # different store and report the projection missing when it had run.
        installs = importlib.import_module("repositories.sdk_repos").SDKInstallationRepository()
        record = _run(installs.get("t1", SITE))

        assert record is not None, "the install signal never reached the verifier"
        assert record["record_type"] == SITE_INSTALL_RECORD_TYPE
        assert record["status"] == "loaded"
        assert record["signals"][SIGNAL_LOADED]["count"] == 1
        assert record["drift_status"] == DRIFT_CURRENT


def test_an_ordinary_batch_leaves_no_install_record():
    """The projection runs on every accepted batch, so the common case has to
    be a miss — not a record created for whatever site happened to be nearby."""
    with _fresh() as env:
        producer = _FakeProducer()
        _ingest(env, [_sdk_event(env.batch, signal=None, event_type="order_completed")], producer)
        installs = importlib.import_module("repositories.sdk_repos").SDKInstallationRepository()
        assert _run(installs.get("t1", SITE)) is None


def test_the_projection_is_skipped_entirely_for_ordinary_batches():
    """Not merely a no-op: an ordinary batch must not allocate a task, because
    this runs on the hot ingestion path for every tenant."""
    assert schedule_install_projection("t1", [{"event_type": "order_completed"}]) is None
    assert schedule_install_projection("t1", []) is None


def test_a_projection_failure_cannot_fail_ingestion():
    """It runs after Bronze durability, so a verifier-side bug must not become
    a 503 for a tenant whose events are already safe."""
    from services.sdk_distribution import install_verifier
    import repositories.sdk_repos as sdk_repos

    class _Boom:
        async def get(self, *_a, **_k):
            raise RuntimeError("projection is broken")

        async def upsert(self, *_a, **_k):
            raise RuntimeError("projection is broken")

    real = sdk_repos.SDKInstallationRepository
    sdk_repos.SDKInstallationRepository = _Boom
    try:
        written = _run(install_verifier.record_install_signals("t1", [_event(SIGNAL_LOADED)]))
    finally:
        sdk_repos.SDKInstallationRepository = real

    assert written == 0, "a failed projection must report nothing written, not raise"


# ── Site installs are not fleet members ──────────────────────────────────────

def test_a_site_install_is_not_counted_as_a_fleet_sdk():
    """Site installs share the table but produce one-shot signals and never a
    heartbeat, so a fleet read that included them would report every correctly
    installed site as a silent SDK."""
    installs = SDKInstallationRepository()
    _run(installs.insert("t-fleet:dev-1", {"tenant_id": "t-fleet", "installation_id": "dev-1"}))
    _run(installs.insert(
        f"t-fleet:{SITE}",
        {"tenant_id": "t-fleet", "installation_id": SITE, "record_type": SITE_INSTALL_RECORD_TYPE},
    ))

    every = _run(installs.list_for_tenant("t-fleet"))
    fleet = _run(installs.list_fleet_for_tenant("t-fleet"))

    assert {r["installation_id"] for r in every} == {"dev-1", SITE}
    assert [r["installation_id"] for r in fleet] == ["dev-1"]


def test_a_legacy_installation_with_no_record_type_is_still_fleet():
    """Every installation written before this field existed is a fleet member.
    Excluding them would silently empty the fleet dashboard on deploy."""
    installs = SDKInstallationRepository()
    _run(installs.insert("t-legacy:old-1", {"tenant_id": "t-legacy", "installation_id": "old-1"}))
    assert [r["installation_id"] for r in _run(installs.list_fleet_for_tenant("t-legacy"))] == ["old-1"]


def test_fleet_health_does_not_count_a_site_install_as_a_silent_sdk():
    """The repository excluding the row is worth nothing if the fleet reads do
    not use it. A site install has no last_seen, so a health read that saw it
    would report it silent — the exact false alarm the marker prevents."""
    with _fresh() as env:
        producer = _FakeProducer()
        _ingest(env, [_sdk_event(env.batch, signal=SIGNAL_LOADED)], producer)

        health = importlib.import_module("services.sdk_health.service")
        service = health.SDKHealthService()

        status = _run(service.get_fleet_status("t1"))
        assert status.total_instances == 0, "a site install was counted as a fleet SDK"
        assert _run(service.detect_silent_sdks("t1")) == []


# ── The routes exist, and are the ones the install page advertises ───────────

def test_the_install_page_advertises_endpoints_that_exist():
    """The install page hands an operator a URL to poll. A verifier endpoint
    that is advertised but unregistered is a 404 at the exact moment someone is
    trying to find out whether their install worked."""
    from services.sdk_distribution.routes import router

    registered = {r.path for r in router.routes}
    for path in ("/v1/sdk/sites/{site_id}/heartbeat", "/v1/sdk/sites/{site_id}/live"):
        assert path in registered, f"{path} is advertised but not registered"


# ── Harness: the real ingestion spine ────────────────────────────────────────

_BACKEND_PREFIXES = (
    "config", "services", "shared", "middleware", "dependencies", "repositories",
)


class _FakeCache:
    def __init__(self) -> None:
        self._store: dict = {}

    async def get(self, key):
        return self._store.get(key)

    async def set_nx(self, key, value, ttl=None) -> bool:
        if key in self._store:
            return False
        self._store[key] = value
        return True

    async def delete(self, key) -> None:
        self._store.pop(key, None)


class _FakeRegistry:
    def __init__(self, cache) -> None:
        self.cache = cache


class _FakeProducer:
    def __init__(self) -> None:
        self.published: list = []

    async def publish_batch(self, events) -> None:
        self.published.extend(events)


def _sdk_event(batch_mod, *, signal, event_type=None):
    """One canonical SDK event, optionally an install signal for SITE."""
    properties = {}
    if signal:
        properties = {
            "siteId": SITE,
            "loaderVersion": LOADER_VERSION,
            "installMode": "cdn_auto",
        }
    return batch_mod.BaseEvent(
        id=f"evt-{signal or event_type}",
        type=event_type or signal,
        timestamp="2026-09-15T10:00:00.000Z",
        sessionId="sess-1",
        anonymousId="anon-1",
        userId="u-1",
        properties=properties,
        context=batch_mod.EventContext(
            library={"name": "@aether/sdk", "version": LOADER_VERSION}
        ),
    )


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


@contextmanager
def _fresh():
    """Fresh, mutually-consistent backend generation with in-memory stores reset."""
    saved = dict(os.environ)
    os.environ["AETHER_ENV"] = "local"
    os.environ.setdefault("JWT_SECRET", "test-secret")
    _evict_backend()
    try:
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        batch = importlib.import_module("services.ingestion.batch")
        env = SimpleNamespace(repos=repos, batch=batch, cache=_FakeCache())
        env.batch.get_registry = lambda: _FakeRegistry(env.cache)
        env.batch.get_identity_resolver = lambda: None
        env.batch._resolve_identity_safe = _noop_async
        yield env
    finally:
        _evict_backend()
        os.environ.clear()
        os.environ.update(saved)


async def _noop_async(*_a, **_k) -> None:
    return None


def _ingest(env, events, producer):
    """Run the spine, then let its fire-and-forget tasks finish.

    The projection is deliberately off the request path, so a test that only
    awaited the response would assert on a record that had not been written yet
    — and would pass for the wrong reason if the hook were removed entirely.
    """
    async def _drive():
        response = await env.batch.ingest_events(
            events,
            tenant_id="t1",
            request_privacy=SimpleNamespace(gpc=False, dnt=False, malformed=()),
            server_context=None,
            granted_consents=frozenset(),
            sent_at=None,
            producer=producer,
        )
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return response

    return _run(_drive())
