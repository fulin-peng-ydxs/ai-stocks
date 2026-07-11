"""筛选方案存取（screen_profile 表）——保存/读取/列出/版本化 + 系统内置方案入库。

混合持久层（stage1·T2）：方案与版本属**用户资产**，落 PostgreSQL（self.pg，占位符 %s），
按 tenant_id+owner_user_id 隔离。本仓库不读行情。
归属上下文：auth 落地前统一默认租户/管理员；之后由请求上下文注入。
系统内置方案（is_preset）跨用户共享语义留阶段三决策，stage1 单一归属者下按归属者存取即可。
"""

from __future__ import annotations

import json
from datetime import datetime

from backend.auth.context import get_current_owner
from backend.common.logging import get_logger
from backend.screening.condition import validate_ast
from backend.screening.presets import PRESET_PROFILES
from backend.services.asset_visibility import (
    ASSET_SCREEN_PROFILE,
    VISIBILITY_PRIVATE,
    decorate_asset_row,
    is_asset_visible,
    make_asset_ref,
    normalize_visibility,
    resolve_asset_ref_or_legacy_id,
    summarize_asset_row,
    visible_params,
    visible_sql,
)
from backend.storage.pg_client import get_pg_client

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

    def _decorate_summary(self, r: dict) -> dict:
        return summarize_asset_row(
            r,
            asset_type=ASSET_SCREEN_PROFILE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
        )

    def _row_to_profile(self, r: dict, *, include_owner: bool = False) -> dict:
        out = decorate_asset_row(
            r,
            asset_type=ASSET_SCREEN_PROFILE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            include_owner=include_owner,
            ref_key="profile_ref",
        )
        out["version"] = int(out["version"])
        out["is_preset"] = bool(out.get("is_preset"))
        out["expression"] = json.loads(out["expression"])
        out["params"] = json.loads(out["params"]) if out.get("params") else {}
        out["published_at"] = str(out["published_at"]) if out.get("published_at") else None
        return out

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
        r = self._row_to_profile(df.iloc[0].to_dict())
        for key in ("asset_ref", "profile_ref", "source", "readonly", "owner_label"):
            r.pop(key, None)
        return r

    def list(self) -> list[dict]:
        df = self.pg.query_df(
            f"SELECT id, name, version, is_preset FROM screen_profile WHERE {self._own} "
            f"ORDER BY is_preset DESC, id", self._op)
        return df.to_dict("records")

    def list_visible(self) -> list[dict]:
        df = self.pg.query_df(
            "SELECT id, tenant_id, owner_user_id, name, version, is_preset, visibility "
            "FROM screen_profile "
            f"WHERE {visible_sql()} "
            "ORDER BY "
            "CASE WHEN tenant_id=%s AND owner_user_id=%s THEN 0 "
            "WHEN is_preset IS TRUE THEN 1 "
            "WHEN visibility='tenant' THEN 2 ELSE 3 END, is_preset DESC, name, id",
            [
                *visible_params(tenant_id=self.tenant_id, owner_user_id=self.owner_user_id),
                self.tenant_id,
                self.owner_user_id,
            ],
        )
        return [self._decorate_summary(r) for r in df.to_dict("records")]

    def get_visible(self, profile_ref_or_id: str, *, include_owner: bool = False) -> dict | None:
        try:
            ref = resolve_asset_ref_or_legacy_id(
                profile_ref_or_id,
                asset_type=ASSET_SCREEN_PROFILE,
                tenant_id=self.tenant_id,
                owner_user_id=self.owner_user_id,
            )
        except ValueError:
            return None
        df = self.pg.query_df(
            "SELECT * FROM screen_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [ref.tenant_id, ref.owner_user_id, ref.asset_id],
        )
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        if not is_asset_visible(row, tenant_id=self.tenant_id, owner_user_id=self.owner_user_id):
            return None
        return self._row_to_profile(row, include_owner=include_owner)

    def set_visibility(
        self,
        profile_ref_or_id: str,
        visibility: str,
        published_by: str | None = None,
    ) -> dict | None:
        visibility = normalize_visibility(visibility)
        ref = resolve_asset_ref_or_legacy_id(
            profile_ref_or_id,
            asset_type=ASSET_SCREEN_PROFILE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
        )
        if ref.tenant_id != self.tenant_id or ref.owner_user_id != self.owner_user_id:
            raise PermissionError("只能修改自己的筛选方案可见性")
        now = datetime.now() if visibility != VISIBILITY_PRIVATE else None
        affected = self.pg.execute(
            "UPDATE screen_profile SET visibility=%s, published_at=%s, published_by=%s, updated_at=%s "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [
                visibility,
                now,
                published_by if visibility != VISIBILITY_PRIVATE else None,
                datetime.now(),
                ref.tenant_id,
                ref.owner_user_id,
                ref.asset_id,
            ],
        )
        if affected == 0:
            return None
        return self.get_visible(profile_ref_or_id)

    def copy_visible(self, profile_ref_or_id: str, new_id: str, new_name: str | None = None) -> int:
        new_id = (new_id or "").strip()
        if not new_id:
            raise ValueError("目标方案 id 不能为空")
        src = self.get_visible(profile_ref_or_id, include_owner=True)
        if not src:
            raise ValueError("方案不存在")
        if self.get(new_id):
            raise ValueError("目标方案已存在，请改名后再复制")
        return self.save(new_id, new_name or f"{src['name']} 副本", src["expression"], src["params"])

    def versions_visible(self, profile_ref_or_id: str) -> dict | None:
        prof = self.get_visible(profile_ref_or_id, include_owner=True)
        if not prof:
            return None
        df = self.pg.query_df(
            "SELECT version, name, expression, saved_at FROM screen_profile_version "
            "WHERE id=%s AND tenant_id=%s AND owner_user_id=%s ORDER BY version DESC",
            [prof["id"], prof["tenant_id"], prof["owner_user_id"]],
        )
        out = []
        for r in df.to_dict("records"):
            r["expression"] = json.loads(r["expression"])
            r["saved_at"] = str(r["saved_at"])
            out.append(r)
        return {"id": prof["id"], "profile_ref": prof["profile_ref"], "versions": out}

    def delete(self, pid: str) -> None:
        """删除方案及其版本历史（PG，按归属）。删除前拦截,防悬空引用(P1)。"""
        self._assert_deletable(pid)
        self.pg.execute(
            f"DELETE FROM screen_profile WHERE id=%s AND {self._own}", [pid, *self._op])
        self.pg.execute(
            f"DELETE FROM screen_profile_version WHERE id=%s AND {self._own}", [pid, *self._op])

    def _assert_deletable(self, pid: str) -> None:
        cur = self.pg.query_df(
            f"SELECT visibility FROM screen_profile WHERE id=%s AND {self._own}", [pid, *self._op])
        if cur.empty:
            return
        if normalize_visibility(cur.iloc[0]["visibility"]) != VISIBILITY_PRIVATE:
            raise ValueError("请先将方案收回为私有再删除")
        # ref 全局唯一(编码 tenant/owner/id),裸 id 仅在本 owner 内唯一,须限归属避免误挡他人同名 id
        ref = make_asset_ref(ASSET_SCREEN_PROFILE, self.tenant_id, self.owner_user_id, pid)
        hit = self.pg.query_df(
            "SELECT 1 FROM backtest_run WHERE profile_id=%s "
            "OR (profile_id=%s AND tenant_id=%s AND owner_user_id=%s) LIMIT 1",
            [ref, pid, self.tenant_id, self.owner_user_id])
        if not hit.empty:
            raise ValueError("该方案被回测记录引用，无法删除，请先删除相关回测")

    def seed_presets(self) -> int:
        """把系统内置方案写入（幂等）。"""
        n = 0
        for p in PRESET_PROFILES:
            self.save(p["id"], p["name"], p["expression"], is_preset=True)
            n += 1
        log.info("系统内置筛选方案入库 %d 个", n)
        return n
