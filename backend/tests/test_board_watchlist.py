"""板块自选：租户隔离、幂等增删与失效板块保留。"""

from __future__ import annotations

from backend.groups.board_watchlist import BoardWatchlistRepo
from backend.services.board_watchlist import BoardWatchlistService


def test_repo_isolates_owner_and_keeps_add_idempotent(pg):
    first = BoardWatchlistRepo(pg, tenant_id="tenant-a", owner_user_id="user-a")
    second = BoardWatchlistRepo(pg, tenant_id="tenant-a", owner_user_id="user-b")
    pg.execute(
        "DELETE FROM board_watchlist WHERE tenant_id=%s AND owner_user_id IN (%s, %s)",
        ["tenant-a", "user-a", "user-b"],
    )
    try:
        assert first.add("309121", "AI PC", "concept") is True
        assert first.add("309121", "AI PC", "concept") is False
        assert second.add("309121", "AI PC", "concept") is True
        assert [row["board_code"] for row in first.list()] == ["309121"]
        assert [row["board_code"] for row in second.list()] == ["309121"]

        assert first.remove("309121") is True
        assert first.remove("309121") is False
        assert first.list() == []
        assert [row["board_code"] for row in second.list()] == ["309121"]
    finally:
        pg.execute(
            "DELETE FROM board_watchlist WHERE tenant_id=%s AND owner_user_id IN (%s, %s)",
            ["tenant-a", "user-a", "user-b"],
        )


class _FakeRepo:
    def __init__(self):
        self.rows = [{
            "board_code": "309121",
            "name": "AI PC",
            "board_type": "concept",
            "added_at": "2026-08-11T10:00:00",
        }]

    def list(self):
        return list(self.rows)

    def add(self, board_code, board_name, board_type):
        return True

    def remove(self, board_code):
        return True


class _MissingMarket:
    def get_sector(self, board_code):
        return None

    def list_sectors(self, **kwargs):
        return {
            "list": [],
            "total": 0,
            "trade_date": "2026-08-11",
            "fund_flow_date": None,
            "page": 1,
            "size": kwargs["size"],
        }


def test_service_rejects_unknown_board_and_retains_stale_snapshot():
    service = BoardWatchlistService(repo=_FakeRepo(), market=_MissingMarket())

    try:
        service.add("missing")
        raise AssertionError("不存在板块必须拒绝加入自选")
    except ValueError as exc:
        assert "板块不存在" in str(exc)

    result = service.list_markets(page=1, size=20)
    assert result["total"] == 1
    assert result["list"][0]["board_code"] == "309121"
    assert result["list"][0]["name"] == "AI PC"
    assert result["list"][0]["available"] is False
