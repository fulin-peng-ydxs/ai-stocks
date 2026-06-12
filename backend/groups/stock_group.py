"""股票分组（个股查询·篮子，M2.4+）——用户手动圈定的一批股票 + 各股加入日期。

模型（决策：每只股各自加入日为涨幅基准）：
  stock_group         分组元信息：名称 / 建组日期 / 说明
  stock_group_member  成员：每只股的加入日期（=最近涨幅基准；建组时默认=建组日期）

涨幅口径：单股 = 加入日(或其后首个交易日)前复权收盘 → 最新收盘；整组 = 各股**等权平均**。
前复权比值与基准无关（close×adj_factor 同比缩放），收益率天然 scale-invariant。
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.duckdb_client import get_client

log = get_logger("groups.stock_group")


class StockGroupRepo:
    def __init__(self, client=None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db
        init_db(self.c)

    # ── 元信息 CRUD ──
    def _new_id(self) -> str:
        return "grp_" + datetime.now().strftime("%Y%m%d%H%M%S%f")

    def create(self, name: str, group_date: date | None, description: str = "",
               codes: list[str] | None = None) -> str:
        if not name or not name.strip():
            raise ValueError("分组名不能为空")
        gid = self._new_id()
        gd = group_date or pd.Timestamp(
            self.c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]).date()
        now = datetime.now()
        self.c.execute(
            "INSERT INTO stock_group (id,name,group_date,description,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)", [gid, name.strip(), gd, description or "", now, now])
        if codes:
            self.add_members(gid, codes, add_date=gd)  # 建组成员默认加入日=建组日期
        return gid

    def update_meta(self, gid: str, name: str | None = None, group_date: date | None = None,
                    description: str | None = None) -> None:
        sets, params = [], []
        if name is not None:
            sets.append("name=?"); params.append(name.strip())
        if group_date is not None:
            sets.append("group_date=?"); params.append(group_date)
        if description is not None:
            sets.append("description=?"); params.append(description)
        if not sets:
            return
        sets.append("updated_at=?"); params.append(datetime.now())
        params.append(gid)
        self.c.execute(f"UPDATE stock_group SET {', '.join(sets)} WHERE id=?", params)

    def delete(self, gid: str) -> None:
        self.c.execute("DELETE FROM stock_group_member WHERE group_id=?", [gid])
        self.c.execute("DELETE FROM stock_group WHERE id=?", [gid])

    # ── 成员 ──
    def add_members(self, gid: str, codes: list[str], add_date: date | None = None) -> int:
        if not codes:
            return 0
        ad = add_date or pd.Timestamp(
            self.c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]).date()
        n = 0
        for code in codes:
            # 已存在则不覆盖其加入日期（保留首次加入基准）
            self.c.execute(
                "INSERT INTO stock_group_member (group_id,code,add_date,note) VALUES (?,?,?,?) "
                "ON CONFLICT (group_id,code) DO NOTHING", [gid, code, ad, ""])
            n += 1
        self.c.execute("UPDATE stock_group SET updated_at=? WHERE id=?", [datetime.now(), gid])
        return n

    def set_member_date(self, gid: str, code: str, add_date: date) -> None:
        self.c.execute("UPDATE stock_group_member SET add_date=? WHERE group_id=? AND code=?",
                       [add_date, gid, code])

    def remove_members(self, gid: str, codes: list[str]) -> None:
        if not codes:
            return
        ph = ",".join("?" * len(codes))
        self.c.execute(f"DELETE FROM stock_group_member WHERE group_id=? AND code IN ({ph})",
                       [gid, *codes])
        self.c.execute("UPDATE stock_group SET updated_at=? WHERE id=?", [datetime.now(), gid])

    # ── 查询 ──
    def list(self) -> list[dict]:
        df = self.c.query_df(
            "SELECT g.id, g.name, g.group_date, g.description, "
            "       (SELECT count(*) FROM stock_group_member m WHERE m.group_id=g.id) AS member_count, "
            "       g.updated_at "
            "FROM stock_group g ORDER BY g.updated_at DESC")
        out = []
        for r in df.to_dict("records"):
            r["group_date"] = str(pd.Timestamp(r["group_date"]).date()) if r.get("group_date") is not None and not pd.isna(r["group_date"]) else None
            r["member_count"] = int(r["member_count"])
            r["updated_at"] = str(r["updated_at"])
            out.append(r)
        return out

    def get(self, gid: str) -> dict | None:
        g = self.c.query_df("SELECT * FROM stock_group WHERE id=?", [gid])
        if g.empty:
            return None
        meta = g.iloc[0].to_dict()
        meta["group_date"] = str(pd.Timestamp(meta["group_date"]).date()) if meta.get("group_date") is not None and not pd.isna(meta["group_date"]) else None
        meta["created_at"] = str(meta["created_at"])
        meta["updated_at"] = str(meta["updated_at"])
        meta["members"] = self._members_with_returns(gid)
        rets = [m["ret"] for m in meta["members"] if m["ret"] is not None]
        meta["avg_ret"] = round(sum(rets) / len(rets), 4) if rets else None
        meta["count"] = len(meta["members"])
        return meta

    def _members_with_returns(self, gid: str) -> list[dict]:
        m = self.c.query_df(
            "SELECT m.code, m.add_date, m.note, sb.name "
            "FROM stock_group_member m LEFT JOIN stock_basic sb ON sb.code=m.code "
            "WHERE m.group_id=? ORDER BY m.add_date, m.code", [gid])
        if m.empty:
            return []
        codes = m["code"].tolist()
        ph = ",".join("?" * len(codes))
        # 各股最新前复权收盘（该股可得的最大交易日）
        last = self.c.query_df(
            f"SELECT code, close*adj_factor AS h, trade_date FROM "
            f"(SELECT *, row_number() OVER (PARTITION BY code ORDER BY trade_date DESC) AS rn "
            f" FROM daily_bar WHERE code IN ({ph})) WHERE rn=1", codes)
        last_h = dict(zip(last["code"], last["h"]))
        last_d = {c: str(pd.Timestamp(d).date()) for c, d in zip(last["code"], last["trade_date"])}
        out = []
        for _, r in m.iterrows():
            code = r["code"]
            ad = pd.Timestamp(r["add_date"]).date() if not pd.isna(r["add_date"]) else None
            entry = None
            if ad is not None:
                e = self.c.query_df(
                    "SELECT close*adj_factor AS h, trade_date FROM daily_bar "
                    "WHERE code=? AND trade_date>=? ORDER BY trade_date LIMIT 1", [code, ad])
                if not e.empty:
                    entry = float(e.iloc[0]["h"])
            lh = last_h.get(code)
            ret = round(float(lh / entry - 1), 4) if entry and lh and entry > 0 else None
            out.append({
                "code": code, "name": r["name"],
                "add_date": str(ad) if ad else None,
                "ret": ret, "last_date": last_d.get(code),
                "note": r["note"] or "",
            })
        return out
