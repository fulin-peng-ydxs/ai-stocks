"""阶段六公开资产 visibility 路由资源码元数据回归。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

_SECRET = "test-secret-stage6-visibility-resource-codes"
_HTTP_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _route_dep_calls(route) -> list:
    return [d.call for d in route.dependant.dependencies if getattr(d, "call", None)]


def _resource_codes(route) -> set[str]:
    codes: set[str] = set()
    for call in _route_dep_calls(route):
        if hasattr(call, "resource_code"):
            codes.add(getattr(call, "resource_code"))
        codes |= set(getattr(call, "resource_codes", set()))
    return codes


def _iter_api_routes(app):
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = (getattr(route, "methods", None) or set()) & _HTTP_VERBS
        if path.startswith("/api/") and methods:
            yield path, methods, route


def test_stage6_visibility_post_routes_expose_publish_resource_codes(client):
    expected = [
        (
            "POST",
            "/api/profiles/{pid}/visibility",
            {"screen-profile:view", "screen-profile:publish-tenant", "screen-profile:publish-public"},
        ),
        (
            "POST",
            "/api/score-profiles/{pid}/visibility",
            {"score-profile:view", "score-profile:publish-tenant", "score-profile:publish-public"},
        ),
        (
            "POST",
            "/api/trade-profiles/{pid}/visibility",
            {"trade-profile:view", "trade-profile:publish-tenant", "trade-profile:publish-public"},
        ),
        (
            "POST",
            "/api/backtest/runs/{run_id}/visibility",
            {"backtest:view", "backtest:publish-tenant", "backtest:publish-public"},
        ),
    ]
    routes = list(_iter_api_routes(client.app))

    for method, path, codes in expected:
        matches = [route for p, methods, route in routes if p == path and method in methods]
        assert matches, f"{method} {path} 路由未注册"
        exposed = set().union(*(_resource_codes(route) for route in matches))
        assert codes <= exposed
