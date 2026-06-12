"""筛选方案存取（screen_profile 表）——保存/读取/列出/版本化 + 预设入库。"""

from __future__ import annotations

import json
from datetime import datetime

from backend.common.logging import get_logger
from backend.screening.condition import validate_ast
from backend.screening.presets import PRESET_PROFILES
from backend.storage.duckdb_client import get_client

log = get_logger("screening.profile")


class ProfileRepo:
    def __init__(self, client=None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db
        init_db(self.c)

    def save(self, pid: str, name: str, expression: dict, params: dict | None = None,
             is_preset: bool = False) -> int:
        """保存/更新方案。**仅当条件/名称实质变更才 version+1 并归档历史**；
        内容未变则原版本返回（避免重复保存/重跑 seed 导致版本虚增）。返回当前版本号。"""
        validate_ast(expression)
        expr_json = json.dumps(expression, ensure_ascii=False)
        cur = self.c.query_df(
            "SELECT version, name, expression FROM screen_profile WHERE id = ?", [pid])
        now = datetime.now()
        if not cur.empty:
            old = cur.iloc[0]
            unchanged = (old["expression"] == expr_json and old["name"] == name)
            if unchanged:
                return int(old["version"])  # 无实质变更，不动版本
            version = int(old["version"]) + 1
            created = self.c.query_df(
                "SELECT created_at FROM screen_profile WHERE id = ?", [pid]).iloc[0]["created_at"]
        else:
            version, created = 1, now
        self.c.execute(
            "INSERT INTO screen_profile (id,name,version,expression,params,is_preset,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (id) DO UPDATE SET "
            "name=EXCLUDED.name, version=EXCLUDED.version, expression=EXCLUDED.expression, "
            "params=EXCLUDED.params, is_preset=EXCLUDED.is_preset, updated_at=EXCLUDED.updated_at",
            [pid, name, version, expr_json,
             json.dumps(params or {}, ensure_ascii=False), is_preset, created, now],
        )
        # 归档该版本快照（幂等）
        self.c.execute(
            "INSERT INTO screen_profile_version (id,version,name,expression,saved_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT (id,version) DO UPDATE SET "
            "name=EXCLUDED.name, expression=EXCLUDED.expression, saved_at=EXCLUDED.saved_at",
            [pid, version, name, expr_json, now],
        )
        return version

    def versions(self, pid: str) -> list[dict]:
        """方案的历史版本（新→旧）。"""
        df = self.c.query_df(
            "SELECT version, name, expression, saved_at FROM screen_profile_version "
            "WHERE id = ? ORDER BY version DESC", [pid])
        out = []
        for r in df.to_dict("records"):
            r["expression"] = json.loads(r["expression"])
            r["saved_at"] = str(r["saved_at"])
            out.append(r)
        return out

    def get(self, pid: str) -> dict | None:
        df = self.c.query_df("SELECT * FROM screen_profile WHERE id = ?", [pid])
        if df.empty:
            return None
        r = df.iloc[0].to_dict()
        r["expression"] = json.loads(r["expression"])
        r["params"] = json.loads(r["params"]) if r.get("params") else {}
        return r

    def list(self) -> list[dict]:
        df = self.c.query_df(
            "SELECT id, name, version, is_preset FROM screen_profile ORDER BY is_preset DESC, id")
        return df.to_dict("records")

    def seed_presets(self) -> int:
        """把内置预设方案写入（幂等）。"""
        n = 0
        for p in PRESET_PROFILES:
            self.save(p["id"], p["name"], p["expression"], is_preset=True)
            n += 1
        log.info("内置预设方案入库 %d 个", n)
        return n
