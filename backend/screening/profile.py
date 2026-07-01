"""筛选方案存取（screen_profile 表）——保存/读取/列出/版本化 + 预设入库。

混合持久层（stage1·T2）：方案与版本属**用户资产**，落 PostgreSQL（self.pg，占位符 %s），
按 tenant_id+owner_user_id 隔离。本仓库不读行情。
归属上下文：auth 落地前统一默认租户/管理员；之后由请求上下文注入。
预设（is_preset）跨用户共享语义留阶段三决策，stage1 单一归属者下按归属者存取即可。
"""

from __future__ import annotations

import json
from datetime import datetime

from backend.common.logging import get_logger
from backend.screening.condition import validate_ast
from backend.screening.presets import PRESET_PROFILES
from backend.storage.pg_client import get_pg_client
from backend.auth.context import get_current_owner

log = get_logger("screening.profile")


class ProfileRepo:
    # 注：第一位保留为 market(DuckDB) 以兼容历史 ProfileRepo(c) 调用；本仓库不用 market。
    def __init__(self, market=None, pg=None, *, tenant_id: str | None = None,
                 owner_user_id: str | None = None):
        self.pg = pg or get_pg_client()
        _ctx_t, _ctx_o = get_current_owner()
        self.tenant_id = tenant_id or _ctx_t
        self.owner_user_id = owner_user_id or _ctx_o

    @property
    def _own(self) -> str:
        return "tenant_id=%s AND owner_user_id=%s"

    @property
    def _op(self) -> list:
        return [self.tenant_id, self.owner_user_id]

    def save(self, pid: str, name: str, expression: dict, params: dict | None = None,
             is_preset: bool = False) -> int:
        """保存/更新方案。**仅当条件/名称实质变更才 version+1 并归档历史**；
        内容未变则原版本返回（避免重复保存/重跑 seed 导致版本虚增）。返回当前版本号。"""
        validate_ast(expression)
        expr_json = json.dumps(expression, ensure_ascii=False)
        cur = self.pg.query_df(
            f"SELECT version, name, expression, created_at FROM screen_profile "
            f"WHERE id=%s AND {self._own}", [pid, *self._op])
        now = datetime.now()
        if not cur.empty:
            old = cur.iloc[0]
            unchanged = (old["expression"] == expr_json and old["name"] == name)
            if unchanged:
                return int(old["version"])  # 无实质变更，不动版本
            version = int(old["version"]) + 1
            created = old["created_at"]
        else:
            version, created = 1, now
        self.pg.execute(
            "INSERT INTO screen_profile "
            "(id,tenant_id,owner_user_id,name,version,expression,params,is_preset,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, id) DO UPDATE SET "
            "name=EXCLUDED.name, version=EXCLUDED.version, expression=EXCLUDED.expression, "
            "params=EXCLUDED.params, is_preset=EXCLUDED.is_preset, updated_at=EXCLUDED.updated_at",
            [pid, self.tenant_id, self.owner_user_id, name, version, expr_json,
             json.dumps(params or {}, ensure_ascii=False), is_preset, created, now],
        )
        # 归档该版本快照（幂等）
        self.pg.execute(
            "INSERT INTO screen_profile_version "
            "(id,tenant_id,owner_user_id,version,name,expression,saved_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, id, version) DO UPDATE SET "
            "name=EXCLUDED.name, expression=EXCLUDED.expression, saved_at=EXCLUDED.saved_at",
            [pid, self.tenant_id, self.owner_user_id, version, name, expr_json, now],
        )
        return version

    def versions(self, pid: str) -> list[dict]:
        """方案的历史版本（新→旧）。"""
        df = self.pg.query_df(
            f"SELECT version, name, expression, saved_at FROM screen_profile_version "
            f"WHERE id=%s AND {self._own} ORDER BY version DESC", [pid, *self._op])
        out = []
        for r in df.to_dict("records"):
            r["expression"] = json.loads(r["expression"])
            r["saved_at"] = str(r["saved_at"])
            out.append(r)
        return out

    def get(self, pid: str) -> dict | None:
        df = self.pg.query_df(
            f"SELECT * FROM screen_profile WHERE id=%s AND {self._own}", [pid, *self._op])
        if df.empty:
            return None
        r = df.iloc[0].to_dict()
        r.pop("tenant_id", None)
        r.pop("owner_user_id", None)
        r["expression"] = json.loads(r["expression"])
        r["params"] = json.loads(r["params"]) if r.get("params") else {}
        return r

    def list(self) -> list[dict]:
        df = self.pg.query_df(
            f"SELECT id, name, version, is_preset FROM screen_profile WHERE {self._own} "
            f"ORDER BY is_preset DESC, id", self._op)
        return df.to_dict("records")

    def delete(self, pid: str) -> None:
        """删除方案及其版本历史（PG，按归属）。"""
        self.pg.execute(
            f"DELETE FROM screen_profile WHERE id=%s AND {self._own}", [pid, *self._op])
        self.pg.execute(
            f"DELETE FROM screen_profile_version WHERE id=%s AND {self._own}", [pid, *self._op])

    def seed_presets(self) -> int:
        """把内置预设方案写入（幂等）。"""
        n = 0
        for p in PRESET_PROFILES:
            self.save(p["id"], p["name"], p["expression"], is_preset=True)
            n += 1
        log.info("内置预设方案入库 %d 个", n)
        return n
