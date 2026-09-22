"""个股列表的次级资产权限隔离。"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

_SECRET = "test-secret-stocks-permissions-0123456789abcdef"


@pytest.fixture()
def client(monkeypatch, pg, market, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    monkeypatch.setattr("backend.api.stocks.get_client", lambda: market)
    from backend.main import create_app

    return TestClient(create_app())


def _auth(user_id: str, tenant_id: str) -> dict[str, str]:
    from backend.auth.jwt_tokens import issue_access

    return {"Authorization": "Bearer " + issue_access(user_id, tenant_id, 0)}


def test_list_stocks_without_group_permission_does_not_read_or_create_groups(
    client,
    monkeypatch,
    pg,
    market,
):
    """只有 stocks:view 时，行情列表不应触碰或泄露自选分组资产。"""
    from backend.services.async_task import AsyncTaskService

    # 本用例只验证分组权限；缺少走势快照时保留任务记录，但不让后台线程越过内存库生命周期。
    monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"stocks_perm_t_{suffix}"
    user_id = f"stocks_perm_u_{suffix}"
    role_id = f"stocks_perm_r_{suffix}"
    group_id = f"stocks_perm_g_{suffix}"
    code = "600000.SH"
    market.execute(
        "INSERT INTO stock_basic "
        "(code,name,exchange,board,list_date,industry,price_limit_pct) "
        "VALUES (?,?,?,?,?,?,?)",
        [code, "浦发银行", "SH", "主板", date(1999, 11, 10), "银行", 0.1],
    )
    market.execute(
        "INSERT INTO daily_bar "
        "(code,trade_date,open,high,low,close,pre_close,volume,amount) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [code, date(2024, 1, 2), 10.0, 10.5, 9.9, 10.2, 10.0, 1000, 10200.0],
    )
    market.execute(
        "INSERT INTO stock_st_status_daily "
        "(code,trade_date,is_st,source,source_ref,quality,captured_at,updated_at) "
        "VALUES (?,DATE '2024-01-02',FALSE,'baostock',"
        "'query_history_k_data_plus:isST','accurate',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        [code],
    )
    pg.execute(
        "INSERT INTO sys_tenant (id,name,status) VALUES (%s,%s,'active')",
        [tenant_id, tenant_id],
    )
    pg.execute(
        "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
        "VALUES (%s,%s,%s,'normal',0,'active')",
        [user_id, tenant_id, user_id],
    )
    pg.execute(
        "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
        "VALUES (%s,%s,%s,'custom',FALSE,FALSE)",
        [role_id, role_id, role_id],
    )
    pg.execute(
        "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)",
        [user_id, role_id],
    )
    pg.execute(
        "INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,'stocks:view')",
        [role_id],
    )
    pg.execute(
        "INSERT INTO stock_group "
        "(id,tenant_id,owner_user_id,name,group_date,description,color,is_default,"
        "created_at,updated_at) "
        "VALUES (%s,%s,%s,'仅本人可见',%s,'','#409eff',FALSE,NOW(),NOW())",
        [group_id, tenant_id, user_id, date(2024, 1, 2)],
    )
    pg.execute(
        "INSERT INTO stock_group_member "
        "(group_id,tenant_id,owner_user_id,code,add_date,note) "
        "VALUES (%s,%s,%s,%s,%s,'')",
        [group_id, tenant_id, user_id, code, date(2024, 1, 2)],
    )

    class ForbiddenStockGroupRepo:
        def __init__(self, *args, **kwargs):
            raise AssertionError("无 stock-group:view 时不得构造 StockGroupRepo")

    monkeypatch.setattr("backend.api.stocks.StockGroupRepo", ForbiddenStockGroupRepo)
    try:
        before = pg.query_df(
            "SELECT count(*) AS n FROM stock_group "
            "WHERE tenant_id=%s AND owner_user_id=%s AND is_default=TRUE",
            [tenant_id, user_id],
        )
        assert int(before.iloc[0]["n"]) == 0

        response = client.get(
            "/api/stocks?trade_date=2024-01-02&page=1&size=10",
            headers=_auth(user_id, tenant_id),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["list"][0]["code"] == code
        assert body["data"]["list"][0]["groups"] == []
        assert body["data"]["list"][0]["st_as_of_date"] == "2024-01-02"

        delisted_code = "600001.SH"
        market.execute(
            "INSERT INTO stock_basic "
            "(code,name,exchange,board,list_date,delist_date,industry,price_limit_pct) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                delisted_code,
                "退市样本",
                "SH",
                "主板",
                date(2000, 1, 1),
                date(2024, 1, 3),
                "测试",
                0.1,
            ],
        )
        market.execute(
            "INSERT INTO stock_st_status_daily "
            "(code,trade_date,is_st,source,source_ref,quality,captured_at,updated_at) "
            "VALUES (?,DATE '2024-01-02',TRUE,'test','delisted-point','accurate',"
            "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            [delisted_code],
        )
        delisted_response = client.get(
            "/api/stocks?board=退市&trade_date=2024-02-01&page=1&size=10",
            headers=_auth(user_id, tenant_id),
        )
        assert delisted_response.status_code == 200
        delisted_row = delisted_response.json()["data"]["list"][0]
        assert delisted_row["is_st"] is True
        assert delisted_row["st_as_of_date"] == "2024-01-02"
        after = pg.query_df(
            "SELECT count(*) AS n FROM stock_group "
            "WHERE tenant_id=%s AND owner_user_id=%s AND is_default=TRUE",
            [tenant_id, user_id],
        )
        assert int(after.iloc[0]["n"]) == 0
    finally:
        pg.execute(
            "DELETE FROM stock_group_member WHERE tenant_id=%s AND owner_user_id=%s",
            [tenant_id, user_id],
        )
        pg.execute(
            "DELETE FROM stock_group WHERE tenant_id=%s AND owner_user_id=%s",
            [tenant_id, user_id],
        )
        pg.execute("DELETE FROM sys_user WHERE id=%s", [user_id])
        pg.execute("DELETE FROM sys_role WHERE id=%s", [role_id])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tenant_id])
