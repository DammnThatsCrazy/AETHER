import pytest

import repositories.repos as repos
import shared.auth.auth as auth
from ingestion.ingestion.observation_envelope import sdk_source_provider
from shared.auth.auth import APIKeyValidator, _build_context_from_key_data


def test_key_platform_reaches_the_tenant_context():
    ctx = _build_context_from_key_data({"tenant_id": "t1", "platform": "web"})
    assert ctx.credential_platform == "web"


def test_missing_platform_stays_unknown():
    assert _build_context_from_key_data({"tenant_id": "t1"}).credential_platform is None


class _Cache:
    def __init__(self):
        self.store = {}

    async def set_json(self, key, value, ttl=None):
        self.store[key] = value

    async def get_json(self, key):
        return self.store.get(key)


@pytest.fixture
def validator(monkeypatch):
    async def unchanged(ctx):
        return ctx

    async def noop(_key_hash):
        return None

    monkeypatch.setattr(auth, "_maybe_apply_billing_plan_tier", unchanged)
    monkeypatch.setattr(auth, "_update_last_used_at", noop)
    return APIKeyValidator(cache=_Cache())


@pytest.mark.asyncio
async def test_registered_platform_round_trips_through_the_cache(validator):
    await validator.register_api_key("ak_live_cache", "t1", platform="react-native")
    ctx = await validator.validate_async("ak_live_cache")
    assert ctx.credential_platform == "react-native"
    assert sdk_source_provider(ctx.credential_platform) == "react_native"


@pytest.mark.asyncio
async def test_platform_round_trips_through_the_durable_lookup(monkeypatch, validator):
    key_hash = APIKeyValidator.hash_key("ak_live_db")
    row = {"key_hash": key_hash, "tenant_id": "t1", "status": "active", "platform": "ios"}

    class _Repo:
        async def find_by_id(self, key_id):
            return row if key_id == key_hash[:12] else None

    monkeypatch.setattr(repos, "APIKeyRepository", _Repo)
    assert (await auth._lookup_api_key_from_db(key_hash))["platform"] == "ios"
    ctx = await validator.validate_async("ak_live_db")
    assert ctx.credential_platform == "ios"
    assert sdk_source_provider(ctx.credential_platform) == "ios"
