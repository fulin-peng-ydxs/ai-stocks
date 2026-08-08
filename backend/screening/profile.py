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
from backend.common.ids import prefixed_readable_id
from backend.common.logging import get_logger
from backend.screening.condition import validate_ast
from backend.screening.presets import PRESET_PROFILES
from backend.services.asset_visibility import (
    ASSET_SCREEN_PROFILE,
    SCOPE_MINE,
    VISIBILITY_PRIVATE,
    decorate_asset_row,
    downgrade_backtest_runs_referencing,
    is_asset_visible,
    make_asset_ref,
    normalize_visibility,
    publish_platform_presets,
    referencing_backtest_runs_by_others,
    resolve_asset_ref_or_legacy_id,
    scoped_query,
    summarize_asset_row,
    visible_params,
    visible_sql,
)
from backend.storage.pg_client import get_pg_client
from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

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

    def list_mine(self) -> list[dict]:
        """下拉专用：只加载「自己的资产」（纯 owner），不含他人公开与平台槽系统内置段；
        平台槽账号下也剔除全部系统预设，包括尚未完成公开校准的历史数据（R3/C2）。"""
        rows, _ = scoped_query(
            self.pg,
            table="screen_profile",
            source=SCOPE_MINE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            public_board_owner=PUBLIC_BOARD_OWNER,
        )
        return [self._decorate_summary(r) for r in rows]

    def browse(self, source: str, q: str | None = None, page: int = 1, page_size: int = 20) -> dict:
        """搜索弹窗浏览：preset（系统内置严格公开）/ tenant / public（强制补集），关键字 + 分页（R5/R14）。"""
        if source not in ("preset", "tenant", "public"):
            raise ValueError("browse 仅支持 preset/tenant/public 来源")
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        rows, total = scoped_query(
            self.pg,
            table="screen_profile",
            source=source,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            public_board_owner=PUBLIC_BOARD_OWNER,
            q=q,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._decorate_summary(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "source": source,
        }

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
        # 收回为私有：他人引用的方案不可收回（会破坏引用它的公开回测的依赖可见性）；
        # 本人引用不拦（owner 可先删回测再收回），与 _assert_no_own_refs 语义对齐。
        if visibility == VISIBILITY_PRIVATE and referencing_backtest_runs_by_others(
            self.pg, asset_type=ASSET_SCREEN_PROFILE, ref=profile_ref_or_id,
            tenant_id=self.tenant_id, owner_user_id=self.owner_user_id,
        ):
            raise ValueError("该方案被其他用户的回测记录引用，无法收回为私有，请先删除相关回测")
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

    def _make_copy_id(self, name: str) -> str:
        base = prefixed_readable_id(name, prefix="screen_")
        new_id = base
        seq = 2
        while self.get(new_id):
            new_id = f"{base}_{seq}"
            seq += 1
        return new_id

    def _insert_copy(self, new_id: str, name: str, expression: dict, params: dict) -> bool:
        """原子插入一条全新 private 副本（version=1）；id 已存在则不写并返回 False，交上层换 id 重试。

        主表 + 版本表在**同一事务同一游标**内写入：`INSERT ... ON CONFLICT DO NOTHING`
        主表 0 行即撞库（换 id 重试）；版本表失败则整体回滚，杜绝「主表残留、无版本历史」的半成品。"""
        now = datetime.now()
        expr_json = json.dumps(expression, ensure_ascii=False)
        with self.pg.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO screen_profile "
                "(id,tenant_id,owner_user_id,name,version,expression,params,is_preset,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,1,%s,%s,false,%s,%s) "
                "ON CONFLICT (tenant_id, owner_user_id, id) DO NOTHING",
                [new_id, self.tenant_id, self.owner_user_id, name, expr_json,
                 json.dumps(params or {}, ensure_ascii=False), now, now],
            )
            if cur.rowcount == 0:
                return False
            # 版本表用普通 INSERT（不 DO NOTHING）：新 id 下若已存在同版本=孤儿数据不一致，
            # 冲突即抛错、整个事务回滚（含刚写的主表），不静默吞成「主表新、版本旧」。
            cur.execute(
                "INSERT INTO screen_profile_version "
                "(id,tenant_id,owner_user_id,version,name,expression,saved_at) "
                "VALUES (%s,%s,%s,1,%s,%s,%s)",
                [new_id, self.tenant_id, self.owner_user_id, name, expr_json, now],
            )
        return True

    def copy_visible(self, profile_ref_or_id: str, new_name: str | None = None) -> dict:
        """复制可见方案为「我的」private（C8）：后端生成唯一 id、名称默认「原名 副本」，
        撞库/并发有限次重试；仅真正插入成功才返回新 id/profile_ref/name/version。"""
        src = self.get_visible(profile_ref_or_id, include_owner=True)
        if not src:
            raise ValueError("方案不存在")
        base_name = (new_name or "").strip() or f"{src['name']} 副本"
        for _ in range(5):
            new_id = self._make_copy_id(base_name)
            if self._insert_copy(new_id, base_name, src["expression"], src["params"]):
                return {
                    "id": new_id,
                    "profile_ref": make_asset_ref(
                        ASSET_SCREEN_PROFILE, self.tenant_id, self.owner_user_id, new_id),
                    "name": base_name,
                    "version": 1,
                }
        raise ValueError("复制失败：目标 id 冲突，请重试")

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
        """删除方案及其版本历史（PG，按归属）。

        单事务原子执行（评审 P2）：① 本人引用检查**恒执行**（无论是否他人引用，防悬空引用指向
        已删 profile）；② 存在他人引用时级联降级其公开/租户 run 为 private（逃生口，跳过
        "先收回 private" 可见性限制——他人 run 不是 owner 的，owner 处置不了）；③ 删除主表+版本表。
        校验在事务外执行（直接抛 ValueError），数据变更在事务内原子提交，任一失败整体回滚。
        """
        # 校验（事务外，ValueError 原样抛给 API 层）：本人引用恒拦；无他人引用则须先收回 private
        self._assert_no_own_refs(pid)
        by_others = referencing_backtest_runs_by_others(
            self.pg, asset_type=ASSET_SCREEN_PROFILE, ref=pid,
            tenant_id=self.tenant_id, owner_user_id=self.owner_user_id)
        if not by_others:
            self._assert_private(pid)
        # 数据变更（单事务原子）：级联降级他人 run（如有）→ 删除主表 + 版本表
        with self.pg.transaction() as conn:
            if by_others:
                downgrade_backtest_runs_referencing(
                    self.pg, asset_type=ASSET_SCREEN_PROFILE, ref=pid,
                    tenant_id=self.tenant_id, owner_user_id=self.owner_user_id, conn=conn)
            with self.pg.cursor_in(conn) as cur:
                cur.execute(
                    f"DELETE FROM screen_profile WHERE id=%s AND {self._own}", [pid, *self._op])
                cur.execute(
                    f"DELETE FROM screen_profile_version WHERE id=%s AND {self._own}", [pid, *self._op])

    def _assert_private(self, pid: str, *, conn=None) -> None:
        """删除前拦截：公开/租户态方案须先收回 private（无他人引用时生效）。"""
        if conn is not None:
            with self.pg.cursor_in(conn) as cur:
                cur.execute(
                    f"SELECT visibility FROM screen_profile WHERE id=%s AND {self._own}",
                    [pid, *self._op])
                r = cur.fetchone()
            vis = r[0] if r else None
        else:
            df = self.pg.query_df(
                f"SELECT visibility FROM screen_profile WHERE id=%s AND {self._own}",
                [pid, *self._op])
            vis = df.iloc[0]["visibility"] if not df.empty else None
        if vis is None:
            return
        if normalize_visibility(vis) != VISIBILITY_PRIVATE:
            raise ValueError("请先将方案收回为私有再删除")

    def _assert_no_own_refs(self, pid: str, *, conn=None) -> None:
        """本人回测引用检查（恒执行，P1 防悬空）：本人引用须先删回测。

        本人引用（新 ref 形态 + 旧裸 id 存量）无论是否他人引用都拦，防止悬空引用指向已删 profile。
        他人引用不在此拦（opaque ref 编码真实归属，无法按 owner 过滤排除；由 delete 级联降级）。
        """
        ref = make_asset_ref(ASSET_SCREEN_PROFILE, self.tenant_id, self.owner_user_id, pid)
        if conn is not None:
            with self.pg.cursor_in(conn) as cur:
                cur.execute(
                    "SELECT 1 FROM backtest_run WHERE (profile_id=%s OR profile_id=%s) "
                    "AND tenant_id=%s AND owner_user_id=%s LIMIT 1",
                    [ref, pid, self.tenant_id, self.owner_user_id])
                hit = cur.fetchone() is not None
        else:
            hit = not self.pg.query_df(
                "SELECT 1 FROM backtest_run WHERE (profile_id=%s OR profile_id=%s) "
                "AND tenant_id=%s AND owner_user_id=%s LIMIT 1",
                [ref, pid, self.tenant_id, self.owner_user_id]).empty
        if hit:
            raise ValueError("该方案仍被回测记录引用，无法删除，请先删除相关回测")

    def seed_presets(self) -> int:
        """把系统内置方案写入；平台槽预设幂等校准为公开只读资产。"""
        n = 0
        for p in PRESET_PROFILES:
            self.save(p["id"], p["name"], p["expression"], is_preset=True)
            n += 1
        publish_platform_presets(
            self.pg,
            table="screen_profile",
            preset_ids=[p["id"] for p in PRESET_PROFILES],
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            public_board_owner=PUBLIC_BOARD_OWNER,
        )
        log.info("系统内置筛选方案入库 %d 个", n)
        return n
