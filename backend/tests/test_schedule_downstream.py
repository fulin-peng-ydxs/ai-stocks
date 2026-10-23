"""直接下游排序：临时 DuckDB 与隔离 PG schema 共用行为回归。"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from psycopg.conninfo import make_conninfo

from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.scheduler import scheduler
from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.pg_client import PostgresClient
from backend.storage.pg_ddl import (
    _TASK_RUNTIME_UPGRADES,
    DDL_ASYNC_TASK_RUNTIME,
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
                    DDL_SCHEDULED_TRIGGER_EVENT_RUNTIME):
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
        'INSERT INTO async_task (id,task_type,params,status,job_id,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?)',
        [tid, 'recompute', runtime_json_param(client, {}), status, parent['id'], now, now])
    with client.transaction():
        scheduler.enqueue_terminal_events(tid, client=client)
    return tid


def ids(result):
    return [job['id'] for job in result['jobs']]


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
    terminal(runtime, parent)
    current = svc.downstream(parent['id'])
    desired = [delayed['id'], b['id'], a['id'], early['id']] + ids(current)[4:]
    svc.reorder_downstream(parent['id'], desired, current['revision'])
    old = runtime.query_df('SELECT * FROM scheduled_trigger_event')
    assert len(old) == 4
    assert old[old.target_job_id != delayed['id']].due_at.nunique() == 1
    # 已等待的事件保留 A→B→early；新事件使用 b→a→early，延迟任务仍最后到期。
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
