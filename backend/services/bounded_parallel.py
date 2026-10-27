"""采集共享有界队列：工作线程取源，主线程准备、收口及取消等待。"""

import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from uuid import uuid4

from backend.datasource.base import thread_cancel_scope
from backend.datasource.observability import observe_work
from backend.services.async_task import TaskCancelled


def run_bounded_parallel(
    items: list,
    worker,
    *,
    concurrency: int,
    ctx,
    wait_label: str,
    on_complete,
    prepare=None,
    on_tick=None,
    transform_batch=None,
    batch_size: int = 1,
    prefetch_next_batch: bool = False,
) -> None:
    """有界执行可取消采集，不预提交全量任务，也不留下终止后的孤儿写线程。

    收到终止时只取消尚未开始的 Future，并等待最多 ``concurrency`` 个在途工作单元
    到达安全边界。工作线程内的数据源限流/重试会读取同一取消检查器，从而跳过后续
    退避和重试；执行器完全退出后，外层才会把任务标记为 interrupted。
    """
    if concurrency <= 1:
        for completed, item in enumerate(items, 1):
            if ctx:
                ctx.check_cancel()
            prepared = prepare(item) if prepare else item
            try:
                with observe_work(getattr(ctx, "request_tracker", None)), thread_cancel_scope(ctx.check_cancel if ctx else None):
                    value = worker(prepared)
                error = None
            except TaskCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 -- 与并发路径相同的失败收口
                value, error = None, exc
            if on_tick:
                on_tick()
            if ctx:
                ctx.check_cancel()
            entry = (completed, prepared, value, error, 0)
            if transform_batch:
                entry = transform_batch([entry])[0]
            on_complete(*entry)
        return
    iterator = iter(items)
    executor = ThreadPoolExecutor(max_workers=concurrency)
    pending: dict = {}
    completed = 0
    last_heartbeat = 0.0
    ready = []
    queued_keys = {}
    last_flush = time.monotonic()
    tracker = getattr(ctx, "request_tracker", None)

    def _flush():
        nonlocal last_flush
        if not ready:
            return
        if ctx:
            ctx.check_cancel()
        if prefetch_next_batch:
            # 只预取下一工作窗口：待提交一批 + 至多 concurrency 个在途单元。
            # prepare 仍在主线程，工作线程可在本批落库期间继续联网。
            while len(pending) < concurrency and _submit_one():
                pass
        with thread_cancel_scope(ctx.check_cancel if ctx else None):
            batch = transform_batch(ready) if transform_batch else ready
        for entry in batch:
            if tracker:
                with tracker.lock:
                    tracker.states.pop(queued_keys.pop(entry[0], None), None)
            if ctx:
                ctx.check_cancel()
            on_complete(*entry)
        ready.clear()
        last_flush = time.monotonic()

    def _run(item, queue_key):
        with observe_work(tracker), thread_cancel_scope(ctx.check_cancel if ctx else None):
            try:
                return worker(item)
            finally:
                if tracker:
                    with tracker.lock:
                        tracker.states[queue_key] = "write_queue"

    def _submit_one() -> bool:
        try:
            item = next(iterator)
        except StopIteration:
            return False
        prepared = prepare(item) if prepare else item
        queue_key = uuid4().hex
        pending[executor.submit(_run, prepared, queue_key)] = (prepared, queue_key)
        return True

    try:
        for _ in range(min(concurrency, len(items))):
            _submit_one()
        while pending or ready:
            if ready and (len(ready) >= min(batch_size, concurrency) or not pending
                          or time.monotonic() - last_flush >= 1):
                _flush()
                while len(pending) < concurrency and _submit_one():
                    pass
            if not pending:
                continue
            if on_tick:
                on_tick()
            if ctx:
                ctx.check_cancel()
            done_futures, _ = wait(set(pending), timeout=0.1, return_when=FIRST_COMPLETED)
            now = time.monotonic()
            if not done_futures:
                if ctx and now - last_heartbeat >= 10:
                    last_heartbeat = now
                    ctx.log(
                        f"{wait_label}等待中：已完成 {completed}/{len(items)}，"
                        f"未完成工作单元 {len(pending)}，待落库 {len(ready)}；"
                        "取源、额度等待及落库状态见请求运行指标"
                    )
                    ctx.flush()
                    if hasattr(ctx, "set_checkpoint"):
                        ctx.set_checkpoint()
                continue
            for future in done_futures:
                item, queue_key = pending.pop(future)
                if ctx:
                    ctx.check_cancel()
                try:
                    value = future.result()
                    error = None
                except TaskCancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 - 单工作单元失败交给调用方记录
                    value = None
                    error = exc
                completed += 1
                queued_keys[completed] = queue_key
                ready.append((completed, item, value, error, len(pending)))
                if ctx:
                    ctx.check_cancel()
                if not transform_batch:
                    _flush()
                    _submit_one()
                elif len(pending) + len(ready) < concurrency:
                    _submit_one()
    except TaskCancelled:
        cancelled = sum(1 for future in pending if future.cancel())
        running = sum(1 for future in pending if not future.done() and not future.cancelled())
        if ctx:
            ctx.log(
                f"终止收尾：已取消 {cancelled} 个排队工作单元，等待 {running} 个工作单元安全结束；未提交结果不登记完成…",
                "warn",
            )
            ctx.flush()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    finally:
        if tracker:
            with tracker.lock:
                for key in queued_keys.values():
                    tracker.states.pop(key, None)
                for _, key in pending.values():
                    tracker.states.pop(key, None)
