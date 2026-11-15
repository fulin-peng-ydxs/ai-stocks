"""直接下游排序：临时 DuckDB 与隔离 PG schema 共用行为回归。"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from psycopg.conninfo import make_conninfo

from backend.common.exceptions import ConflictError, NotFoundError, StorageError, ValidationError
from backend.scheduler import scheduler
from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.pg_client import PostgresClient
from backend.storage.pg_ddl import (
    _TASK_RUNTIME_UPGRADES,
    DDL_ASYNC_TASK_RUNTIME,
    DDL_SCHEDULED_JOB_DEPENDENCY_RUNTIME,
    DDL_SCHEDULED_JOB_RUNTIME,
    DDL_SCHEDULED_TRIGGER_EVENT_RUNTIME,
    DDL_TASK_LOG_RUNTIME,
)
from backend.storage.task_runtime import PostgresTaskRuntimeClient, runtime_json_param


@pytest.fixture(params=['duckdb', 'postgres'])
def runtime(request, tmp_path):
    if request.param == 'duckdb':
        with DuckDBClient(db_path=str(tmp_path / 'runtime.duckdb')) as client:
            init_db(client)
            yield client
        return
    # 不使用全局 pg 夹具：只在随机 schema 建本测试所需运行态表，不初始化真实菜单/角色。
    admin = PostgresClient()
    if not admin.ping():
        admin.close()
        pytest.skip('PostgreSQL 未就绪')
    schema = 'pytest_downstream_' + uuid.uuid4().hex
    admin.execute(f'CREATE SCHEMA {schema}')
    scoped = PostgresClient(make_conninfo(admin.conninfo, options=f'-csearch_path={schema}'))
    try:
        for ddl in (DDL_ASYNC_TASK_RUNTIME, DDL_TASK_LOG_RUNTIME, DDL_SCHEDULED_JOB_RUNTIME,
                    DDL_SCHEDULED_JOB_DEPENDENCY_RUNTIME, DDL_SCHEDULED_TRIGGER_EVENT_RUNTIME):
            scoped.execute(ddl)
        yield PostgresTaskRuntimeClient(scoped)
    finally:
        scoped.close()
        admin.execute(f'DROP SCHEMA {schema} CASCADE')
        admin.close()


def root(svc, name='上游'):
    return svc.create(name=name, task_type='recompute', params={}, freq_type='daily',
                      freq_config={'time': '16:00'}, trading_day_only=False, enabled=False)


def child(svc, parent, name, *, enabled=True, delay=0, condition='success'):
    return svc.create(name=name, task_type='recompute', params={}, freq_type=None, freq_config={},
                      trigger_mode='dependency', dependency_job_id=parent['id'],
                      dependency_condition=condition,
                      dependency_delay={'value': delay, 'unit': 'second'},
                      trading_day_only=False, enabled=enabled)


def terminal(client, parent, *, status='done'):
    tid = 'pytest_task_' + uuid.uuid4().hex
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    client.execute(
        'INSERT INTO async_task (id,task_type,params,status,progress,job_id,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?,?)',
        [tid, 'recompute', runtime_json_param(client, {}), status, 1.0, parent['id'], now, now])
    with client.transaction():
        scheduler.enqueue_terminal_events(tid, client=client)
    return tid


def ids(result):
    return [job['id'] for job in result['jobs']]


def multi_child(svc, parents, name='共享下游', *, condition='success'):
    return svc.create(
        name=name, task_type='recompute', params={}, freq_type=None, freq_config={},
        trigger_mode='dependency', dependency_job_ids=[job['id'] for job in parents],
        dependency_condition=condition, dependency_delay={'value': 0, 'unit': 'second'},
        trading_day_only=False, enabled=True)


def edit_fields(job, **changes):
    return {**{key: job[key] for key in (
        'name', 'task_type', 'params', 'freq_type', 'freq_config', 'trigger_mode',
        'dependency_job_ids', 'dependency_condition', 'dependency_delay', 'retry_config',
        'trading_day_only', 'enabled')}, **changes}


def test_trigger_records_include_all_sources_without_duplicate_tasks(runtime):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    job, other = root(svc), root(svc, '其他调度')
    now = datetime.now(ZoneInfo('Asia/Shanghai'))

    def task(tid, source, status, offset, *, job_id=None, event_id=None):
        created = now + timedelta(seconds=offset)
        runtime.execute(
            'INSERT INTO async_task (id,task_type,status,job_id,trigger_source,trigger_event_id,'
            'created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
            [tid, 'recompute', status, job_id or job['id'], source, event_id, created, created])

    task('manual', 'manual', 'failed', 1)
    task('scheduled', 'scheduled', 'running', 2)
    task('unrelated', 'manual', 'done', 99, job_id=other['id'])
    task('dependency', 'dependency', 'done', 3, event_id='dependency-event')
    # 旧数据可能仅有 task_id 关联；同样不能重复展示任务。
    task('retry', 'retry', 'pending', 4)
    for kind, offset in [('dependency', 3), ('retry', 4)]:
        created = now + timedelta(seconds=offset)
        runtime.execute(
            'INSERT INTO scheduled_trigger_event (id,source_task_id,source_status,target_job_id,'
            'trigger_kind,retry_count,due_at,dispatched_at,status,task_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            [f'{kind}-event', 'manual', 'failed', job['id'], kind, int(kind == 'retry'),
             created, created, 'dispatched', kind, created, created])
    # 已创建任务但事件尚未回填 task_id 的恢复窗口，以 trigger_event_id 去重。
    runtime.execute("UPDATE scheduled_trigger_event SET task_id=NULL WHERE id='dependency-event'")
    records = svc.list_events(job['id'])
    assert [r['id'] for r in records] == [
        'retry-event', 'dependency-event', 'task:scheduled', 'task:manual']
    assert [r['trigger_kind'] for r in records] == ['retry', 'dependency', 'scheduled', 'manual']
    assert records[0]['task_status'] == 'pending'
    assert records[0]['retry_count'] == 1
    assert records[2]['task_status'] == 'running'
    assert records[3]['task_status'] == 'failed'
    assert records[3]['status'] == 'dispatched'
    assert records[3]['source_task_id'] is None
    assert records[3]['source_status'] is None
    assert records[3]['due_at'] is None  # 不伪造未存储的定时计划时间。
    assert records[3]['dispatched_at'] is not None
    assert [r['id'] for r in svc.list_events(job['id'], 2)] == [r['id'] for r in records[:2]]
    assert svc.list_events(other['id'])[0]['task_id'] == 'unrelated'


def test_trigger_records_limit_is_global_bounded_and_stable(runtime):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    job = root(svc)
    assert svc.list_events(job['id']) == []
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    for i in range(205):
        runtime.execute(
            'INSERT INTO async_task (id,task_type,status,job_id,trigger_source,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?)',
            [f'task-{i:03}', 'recompute', 'done', job['id'],
             'manual' if i % 2 else 'scheduled', now, now])
    records = svc.list_events(job['id'], 999)
    assert len(records) == 200
    assert records[0]['task_id'] == 'task-204'
    assert records[-1]['task_id'] == 'task-005'
    assert len(svc.list_events(job['id'])) == 100
    assert len(svc.list_events(job['id'], 0)) == 1


def test_multi_upstream_each_fires_and_same_attempt_is_idempotent(runtime, monkeypatch):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    a, b = root(svc, 'A'), root(svc, 'B')
    c = multi_child(svc, [a, b, a])
    assert set(c['dependency_job_ids']) == {a['id'], b['id']}
    assert [p['name'] for p in c['dependency_jobs']] == ['A', 'B']
    assert '任一上游（A、B）' in c['trigger_text']
    task_a, task_b = terminal(runtime, a), terminal(runtime, b)
    scheduler.enqueue_terminal_events(task_a, client=runtime)
    events = svc.list_events(c['id'])
    assert len(events) == 2
    assert {e['source_task_id'] for e in events} == {task_a, task_b}
    assert {e['source_job_name'] for e in events} == {'A', 'B'}
    assert all(e['trigger_condition'] == 'success' for e in events)
    # A 的失败不命中成功条件；人工终止不传播。
    terminal(runtime, a, status='failed')
    terminal(runtime, b, status='interrupted')
    assert len(svc.list_events(c['id'])) == 2
    created = []
    busy = {'value': True}
    def create(_self, *args, **kwargs):
        if busy['value']:
            raise ConcurrentTaskError('busy', 'recompute')
        created.append(kwargs)
        return 'task_' + uuid.uuid4().hex
    monkeypatch.setattr(scheduler, '_runtime_client', lambda: runtime)
    monkeypatch.setattr(AsyncTaskService, 'create', create)
    assert scheduler.dispatch_due_events() == 0
    assert {e['status'] for e in svc.list_events(c['id'])} == {'waiting'}
    # 去掉一个上游后，已持久化事件仍使用生成时快照可靠分发。
    svc.update(c['id'], **edit_fields(c, dependency_job_ids=[a['id']]))
    busy['value'] = False
    assert scheduler.dispatch_due_events() == 2
    assert {task['parent_task_id'] for task in created} == {task_a, task_b}
    assert {task['job_id'] for task in created} == {c['id']}
    assert scheduler.dispatch_due_events() == 0


def test_multi_upstream_independent_orders_and_relationship_edits(runtime):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    a, b, d = root(svc, 'A'), root(svc, 'B'), root(svc, 'D')
    c = multi_child(svc, [a, b])
    x, y = child(svc, a, 'X'), child(svc, b, 'Y')
    a_before, b_before = svc.downstream(a['id']), svc.downstream(b['id'])
    svc.reorder_downstream(a['id'], [x['id'], c['id']], a_before['revision'])
    b_after = svc.downstream(b['id'])
    assert b_after['revision'] == b_before['revision']
    assert ids(b_after) == ids(b_before)
    assert [job['dependency_order'] for job in b_after['jobs']] == [0, 1]
    saved = svc.update(c['id'], **edit_fields(c, name='共享下游改名',
                                            dependency_job_ids=[a['id'], b['id'], d['id']]))
    assert ids(svc.downstream(a['id'])) == [x['id'], c['id']]
    assert ids(svc.downstream(b['id'])) == [c['id'], y['id']]
    assert ids(svc.downstream(d['id'])) == [c['id']]
    svc.update(c['id'], **edit_fields(saved, dependency_job_ids=[a['id']]))
    assert ids(svc.downstream(b['id'])) == [y['id']]
    with pytest.raises(ConflictError):
        svc.reorder_downstream(b['id'], ids(b_before), b_before['revision'])
    svc.delete(y['id'])
    svc.delete(b['id'])
    svc.update(c['id'], **edit_fields(saved, trigger_mode='time', freq_type='daily',
                                    freq_config={'time': '17:00'}))
    assert svc.get(c['id'])['dependency_job_ids'] == []
    assert ids(svc.downstream(a['id'])) == [x['id']]
    # 重复初始化不能把已经解除的旧单上游投影恢复为依赖边。
    if isinstance(runtime, PostgresTaskRuntimeClient):
        for sql in _TASK_RUNTIME_UPGRADES:
            runtime.execute(sql)
    else:
        init_db(runtime)
    assert svc.get(c['id'])['dependency_job_ids'] == []


def test_multi_upstream_graph_validation_and_delete_protection(runtime):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    a = root(svc, 'A')
    b, c = multi_child(svc, [a], 'B'), multi_child(svc, [a], 'C')
    d = multi_child(svc, [b, c], 'D')  # 菱形共享祖先合法。
    for invalid in ([], ['missing'], [d['id']], [a['id'], 'missing']):
        with pytest.raises(ValueError):
            svc.update(d['id'], **edit_fields(d, dependency_job_ids=invalid))
    with pytest.raises(ValueError, match='循环依赖'):
        svc.update(a['id'], **edit_fields(a, trigger_mode='dependency',
                                        dependency_job_ids=[d['id']],
                                        dependency_condition='success'))
    # 环路仅位于第二个上游分支也必须拒绝。
    with pytest.raises(ValueError, match='循环依赖'):
        svc.update(c['id'], **edit_fields(c, dependency_job_ids=[a['id'], d['id']]))
    for parent in (b, c):
        with pytest.raises(ValueError, match='仍被以下任务依赖'):
            svc.delete(parent['id'])
    assert set(svc.get(d['id'])['dependency_job_ids']) == {b['id'], c['id']}
    svc.delete(d['id'])
    assert svc.downstream(b['id'])['jobs'] == []
    assert svc.downstream(c['id'])['jobs'] == []


def test_dependency_relation_write_failure_rolls_back_job_definition(runtime, monkeypatch):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    a, b = root(svc, 'A'), root(svc, 'B')
    c = multi_child(svc, [a, b])
    before = svc.get(c['id'])
    original = runtime.executemany
    def fail_edge(sql, rows):
        if sql.startswith('INSERT INTO scheduled_job_dependency'):
            raise RuntimeError('模拟关系写入失败')
        return original(sql, rows)
    monkeypatch.setattr(runtime, 'executemany', fail_edge)
    with pytest.raises(StorageError, match='模拟关系写入失败'):
        svc.update(c['id'], **edit_fields(c, name='不应保存', dependency_job_ids=[b['id']]))
    assert svc.get(c['id']) == before


def test_legacy_single_upstream_backfill_is_idempotent(runtime):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    a = root(svc, '存量上游')
    c = child(svc, a, '存量下游')
    runtime.execute('DELETE FROM scheduled_job_dependency')
    for _ in range(2):
        if isinstance(runtime, PostgresTaskRuntimeClient):
            for sql in _TASK_RUNTIME_UPGRADES:
                runtime.execute(sql)
        else:
            init_db(runtime)
    assert svc.get(c['id'])['dependency_job_ids'] == [a['id']]
    assert ids(svc.downstream(a['id'])) == [c['id']]


def test_frozen_legacy_duckdb_dependency_read_does_not_create_table(tmp_path):
    from backend.storage.task_runtime_migration import _duck_frames
    with DuckDBClient(db_path=str(tmp_path / 'frozen.duckdb')) as source:
        init_db(source)
        svc = scheduler.ScheduledJobService(source, initialize=False)
        a = root(svc, '旧上游')
        c = child(svc, a, '旧下游')
        source.execute('DROP TABLE scheduled_job_dependency')
        frames = _duck_frames(source)
        assert frames['scheduled_job_dependency'].to_dict('records') == [{
            'upstream_job_id': a['id'], 'downstream_job_id': c['id'], 'dependency_order': 0,
        }]
        assert source.query_df("SELECT * FROM information_schema.tables "
                               "WHERE table_name='scheduled_job_dependency'").empty


def test_schedule_api_accepts_multi_upstream_and_returns_all_options(runtime, monkeypatch):
    from backend.api.data_admin import ScheduledJobIn, schedules_create, schedules_update
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    a, b = root(svc, 'A'), root(svc, 'B')
    monkeypatch.setattr(scheduler, '_runtime_client', lambda: runtime)
    body = ScheduledJobIn(
        name='API共享任务', task_type='verify', trigger_mode='dependency',
        dependency_job_ids=[a['id'], b['id']], dependency_condition='completion',
        trading_day_only=False, enabled=False)
    created = schedules_create(body).data
    assert set(created['dependency_job_ids']) == {a['id'], b['id']}
    page = svc.list_page(page=1, size=10, sort_by='freq', sort_order='asc')
    item = next(j for j in page['jobs'] if j['id'] == created['id'])
    assert {p['name'] for p in item['dependency_jobs']} == {'A', 'B'}
    updated = schedules_update(created['id'], body.model_copy(
        update={'dependency_job_ids': [b['id']]})).data
    assert updated['dependency_job_ids'] == [b['id']]


def test_multi_upstream_runtime_migration_round_trip(runtime, tmp_path, monkeypatch):
    if not isinstance(runtime, PostgresTaskRuntimeClient):
        pytest.skip('运行态迁移需隔离 PG schema')
    from backend.storage import pg_ddl
    from backend.storage import task_runtime_migration as migration
    runtime.pg.execute(pg_ddl.DDL_STORAGE_MIGRATION)
    monkeypatch.setattr(pg_ddl, 'init_pg_db', lambda _pg: None)
    with DuckDBClient(db_path=str(tmp_path / 'source.duckdb')) as source:
        init_db(source)
        svc = scheduler.ScheduledJobService(source, initialize=False)
        a, b = root(svc, 'A'), root(svc, 'B')
        c = multi_child(svc, [a, b])
        x = child(svc, a, 'X')
        task_id = terminal(source, a)
        source.execute(
            "INSERT INTO task_log (id,task_id,seq,ts,level,message) VALUES (?,?,?,?,?,?)",
            [79, task_id, 1, datetime.now(ZoneInfo('Asia/Shanghai')), 'info', '迁移日志'])
        current = svc.downstream(a['id'])
        svc.reorder_downstream(a['id'], [x['id'], c['id']], current['revision'])
        before = source.query_df('SELECT * FROM scheduled_job_dependency ORDER BY 1,2')
        report = migration.migrate_task_runtime_to_postgres(duck=source, pg=runtime.pg)
        assert report['duckdb_counts'] == report['postgres_counts']
        assert set(scheduler.ScheduledJobService(runtime, initialize=False)
                   .get(c['id'])['dependency_job_ids']) == {a['id'], b['id']}
        migration.rollback_task_runtime_to_duckdb(
            confirm_marker=migration.TASK_RUNTIME_MIGRATION_MARKER, duck=source, pg=runtime.pg)
        after = source.query_df('SELECT * FROM scheduled_job_dependency ORDER BY 1,2')
        assert after.equals(before)
        assert runtime.query_df('SELECT * FROM scheduled_job_dependency').empty
        assert int(source.query_df("SELECT nextval('seq_task_log') AS id").iloc[0]['id']) == 80


def test_downstream_complete_set_validation_and_revision(runtime):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    parent = root(svc)
    children = [child(svc, parent, str(i), enabled=i != 2) for i in range(23)]
    grandchild = child(svc, children[0], '间接下游')
    current = svc.downstream(parent['id'])
    assert ids(current) == [job['id'] for job in children]
    assert grandchild['id'] not in ids(current)
    assert current['jobs'][2]['enabled'] is False
    expected = list(reversed(ids(current)))
    for invalid in (expected[:-1], expected + [expected[0]], expected[:-1] + [grandchild['id']]):
        with pytest.raises(ValidationError):
            svc.reorder_downstream(parent['id'], invalid, current['revision'])
    assert ids(svc.downstream(parent['id'])) == ids(current)
    saved = svc.reorder_downstream(parent['id'], expected, current['revision'])
    assert ids(saved) == expected
    with pytest.raises(ConflictError):
        svc.reorder_downstream(parent['id'], ids(current), current['revision'])
    child(svc, parent, '新增下游')
    with pytest.raises(ConflictError):
        svc.reorder_downstream(parent['id'], expected, saved['revision'])
    with pytest.raises(NotFoundError):
        svc.downstream('不存在')


def test_normal_edit_preserves_order_move_appends_and_enable_preserves_revision(runtime):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    parent, other = root(svc), root(svc, '另一上游')
    a, b = child(svc, parent, 'A'), child(svc, parent, 'B')
    c = child(svc, other, 'C')
    initial = svc.downstream(parent['id'])
    saved = svc.reorder_downstream(parent['id'], [b['id'], a['id']], initial['revision'])
    svc.set_enabled(a['id'], False)
    assert svc.downstream(parent['id'])['revision'] == saved['revision']
    fields = {key: b[key] for key in (
        'task_type', 'params', 'freq_type', 'freq_config', 'trigger_mode', 'dependency_job_id',
        'dependency_condition', 'dependency_delay', 'retry_config', 'trading_day_only', 'enabled')}
    svc.update(b['id'], name='改名', **fields)
    assert ids(svc.downstream(parent['id'])) == [b['id'], a['id']]
    svc.update(b['id'], name='移动', **{**fields, 'dependency_job_id': other['id']})
    assert ids(svc.downstream(other['id'])) == [c['id'], b['id']]
    assert ids(svc.downstream(parent['id'])) == [a['id']]


def test_snapshot_delay_conditions_and_waiting_slot(runtime, monkeypatch):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    parent = root(svc)
    a, b = child(svc, parent, 'A'), child(svc, parent, 'B')
    early = child(svc, parent, '更早到期')
    delayed = child(svc, parent, '晚到期', delay=20)
    child(svc, parent, '失败分支', condition='failure')
    child(svc, parent, '停用', enabled=False)
    # 调度时间显式推进，不让慢机器上建任务/重排的耗时跨过 20 秒延迟边界。
    clock = {"now": datetime(2026, 11, 16, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)}
    monkeypatch.setattr(scheduler, "shanghai_now_naive", lambda: clock["now"])
    terminal(runtime, parent)
    current = svc.downstream(parent['id'])
    desired = [delayed['id'], b['id'], a['id'], early['id']] + ids(current)[4:]
    svc.reorder_downstream(parent['id'], desired, current['revision'])
    old = runtime.query_df('SELECT * FROM scheduled_trigger_event')
    assert len(old) == 4
    assert old[old.target_job_id != delayed['id']].due_at.nunique() == 1
    # 已等待的事件保留 A→B→early；新事件使用 b→a→early，延迟任务仍最后到期。
    clock["now"] += timedelta(seconds=1)
    newer = terminal(runtime, parent)
    created = []
    busy = {'value': True}
    def create(_self, *args, **kwargs):
        if busy['value']:
            raise ConcurrentTaskError('busy', 'recompute')
        created.append(kwargs['job_id'])
        return 'task_' + uuid.uuid4().hex
    monkeypatch.setattr(scheduler, '_runtime_client', lambda: runtime)
    monkeypatch.setattr(AsyncTaskService, 'create', create)
    assert scheduler.dispatch_due_events() == 0
    assert set(runtime.query_df('SELECT status FROM scheduled_trigger_event').status) == {'waiting'}
    busy['value'] = False
    assert scheduler.dispatch_due_events() == 6
    assert created == [a['id'], b['id'], early['id'], b['id'], a['id'], early['id']]
    new = runtime.query_df('SELECT * FROM scheduled_trigger_event WHERE source_task_id=?', [newer])
    assert new.loc[new.target_job_id == delayed['id'], 'dispatch_order'].iloc[0] == 0
    assert set(runtime.query_df("SELECT status FROM scheduled_trigger_event WHERE target_job_id=?",
                                [delayed['id']]).status) == {'waiting'}
    clock["now"] += timedelta(seconds=21)
    assert scheduler.dispatch_due_events() == 2
    assert created[-2:] == [delayed['id'], delayed['id']]
    assert set(runtime.query_df('SELECT status FROM scheduled_trigger_event').status) == {'dispatched'}


def test_more_than_one_claim_batch_keeps_order_after_pg_returning_shuffle(runtime, monkeypatch):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    parent = root(svc)
    children = [child(svc, parent, f'下游{i}') for i in range(61)]
    current = svc.downstream(parent['id'])
    expected = list(reversed(ids(current)))
    svc.reorder_downstream(parent['id'], expected, current['revision'])
    terminal(runtime, parent)
    if isinstance(runtime, PostgresTaskRuntimeClient):
        claim = runtime.claim_due_events
        monkeypatch.setattr(runtime, 'claim_due_events',
                            lambda **kwargs: claim(**kwargs).iloc[::-1])
    created = []
    monkeypatch.setattr(scheduler, '_runtime_client', lambda: runtime)
    monkeypatch.setattr(AsyncTaskService, 'create', lambda self, *args, **kwargs:
                        created.append(kwargs['job_id']) or 'task_' + uuid.uuid4().hex)
    assert scheduler.dispatch_due_events() == 50
    assert scheduler.dispatch_due_events() == 11
    assert created == expected
    assert len(children) == len(created)


def test_pg_upgrade_is_idempotent_and_does_not_reorder_existing_custom_ranks(runtime):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    parent = root(svc)
    a, b = child(svc, parent, 'A'), child(svc, parent, 'B')
    runtime.execute('UPDATE scheduled_job SET dependency_order=NULL')
    if isinstance(runtime, PostgresTaskRuntimeClient):
        for sql in _TASK_RUNTIME_UPGRADES:
            runtime.execute(sql)
    else:
        init_db(runtime)
    assert ids(svc.downstream(parent['id'])) == [a['id'], b['id']]
    current = svc.downstream(parent['id'])
    svc.reorder_downstream(parent['id'], [b['id'], a['id']], current['revision'])
    if isinstance(runtime, PostgresTaskRuntimeClient):
        for sql in _TASK_RUNTIME_UPGRADES:
            runtime.execute(sql)
    else:
        init_db(runtime)
    assert ids(svc.downstream(parent['id'])) == [b['id'], a['id']]


def test_concurrent_reorders_with_same_revision_only_one_succeeds(runtime):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    parent = root(svc)
    children = [child(svc, parent, str(i)) for i in range(3)]
    current = svc.downstream(parent['id'])
    barrier = threading.Barrier(2)
    outcomes = []
    def reorder(order):
        barrier.wait(timeout=3)
        try:
            svc.reorder_downstream(parent['id'], order, current['revision'])
            outcomes.append('saved')
        except ConflictError:
            outcomes.append('conflict')
    original = [job['id'] for job in children]
    threads = [threading.Thread(target=reorder, args=(order,))
               for order in (original[::-1], original[1:] + original[:1])]
    for worker in threads:
        worker.start()
    for worker in threads:
        worker.join(timeout=5)
        assert not worker.is_alive()
    assert sorted(outcomes) == ['conflict', 'saved']


def test_reorder_storage_failure_rolls_back_all_ranks(runtime, monkeypatch):
    from backend.common.exceptions import StorageError
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    parent = root(svc)
    children = [child(svc, parent, str(i)) for i in range(3)]
    before = svc.downstream(parent['id'])
    def partial_failure(sql, rows):
        runtime.execute(sql, list(rows[0]))
        raise StorageError('模拟第二条更新失败')
    monkeypatch.setattr(runtime, 'executemany', partial_failure)
    with pytest.raises(StorageError):
        svc.reorder_downstream(parent['id'], [job['id'] for job in children][::-1], before['revision'])
    assert svc.downstream(parent['id']) == before


def test_recovery_retains_order_and_one_failed_dispatch_does_not_block_siblings(runtime, monkeypatch):
    svc = scheduler.ScheduledJobService(runtime, initialize=False)
    parent = svc.create(
        name='可重试上游', task_type='recompute', params={}, freq_type='daily',
        freq_config={'time': '16:00'}, trading_day_only=False, enabled=False,
        retry_config={'enabled': True, 'condition': 'failure',
                      'delay': {'value': 0, 'unit': 'second'}, 'max_retries': 1})
    runtime.execute('UPDATE scheduled_job SET enabled=true WHERE id=?', [parent['id']])
    a, b = child(svc, parent, 'A', condition='failure'), child(svc, parent, 'B', condition='failure')
    current = svc.downstream(parent['id'])
    saved = svc.reorder_downstream(parent['id'], [b['id'], a['id']], current['revision'])
    terminal(runtime, parent, status='failed')
    snapshot = runtime.query_df(
        'SELECT id,due_at,created_at,dispatch_order FROM scheduled_trigger_event ORDER BY id')
    runtime.execute("UPDATE scheduled_trigger_event SET status='dispatching'")
    # 恢复时定义顺序已改变；旧事件仍按认领前的快照恢复，不能回读当前顺序。
    svc.reorder_downstream(parent['id'], [a['id'], b['id']], saved['revision'])
    restarted = scheduler.ScheduledJobService(runtime, initialize=False)
    assert restarted.recover_events() == 3
    assert restarted.recover_events() == 0
    restored = runtime.query_df(
        'SELECT id,due_at,created_at,dispatch_order FROM scheduled_trigger_event ORDER BY id')
    assert restored.equals(snapshot)
    attempts = []
    def create(_self, *args, **kwargs):
        attempts.append(kwargs['job_id'])
        if kwargs['job_id'] == b['id']:
            raise RuntimeError('模拟单个下游分发故障')
        return 'task_' + uuid.uuid4().hex
    monkeypatch.setattr(scheduler, '_runtime_client', lambda: runtime)
    monkeypatch.setattr(AsyncTaskService, 'create', create)
    assert scheduler.dispatch_due_events() == 2
    assert attempts == [b['id'], a['id'], parent['id']]
    events = runtime.query_df('SELECT target_job_id,status FROM scheduled_trigger_event')
    assert dict(zip(events.target_job_id, events.status, strict=True)) == {
        b['id']: 'failed', a['id']: 'dispatched', parent['id']: 'dispatched',
    }
