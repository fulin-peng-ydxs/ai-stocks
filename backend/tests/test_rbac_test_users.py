from backend.devtools.rbac_test_users import DEBUG_USERS, _ensure_users


class _RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, list[object]]] = []

    def execute(self, sql: str, params: list[object]) -> None:
        self.statements.append((sql, params))

    def fetchone(self):
        return None


def test_ensure_users_reactivates_soft_deleted_debug_accounts() -> None:
    cursor = _RecordingCursor()

    _ensure_users(cursor, password_hash="test-hash", reset_password=True)

    upserts = [
        (sql, params)
        for sql, params in cursor.statements
        if sql.startswith("INSERT INTO sys_user ")
    ]
    assert len(upserts) == len(DEBUG_USERS)
    assert all("status='active',deleted_at=NULL" in sql for sql, _params in upserts)
