"""PostgreSQL 异常识别辅助。"""

from __future__ import annotations

from psycopg import errors


def unique_violation_constraint(exc: BaseException) -> str | None:
    """沿异常链查找唯一约束冲突并返回约束/索引名。"""
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, errors.UniqueViolation):
            return current.diag.constraint_name
        current = current.__cause__ or current.__context__
    return None
