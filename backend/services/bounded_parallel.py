"""采集共享有界队列：工作线程取源，主线程准备、收口及取消等待。"""

import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from backend.datasource.base import thread_cancel_scope
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
                with thread_cancel_scope(ctx.check_cancel if ctx else None):
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
            on_complete(completed, prepared, value, error, 0)
        return
    iterator = iter(items)
    executor = ThreadPoolExecutor(max_workers=concurrency)
    pending: dict = {}
    completed = 0
    last_heartbeat = 0.0

    def _run(item):
        with thread_cancel_scope(ctx.check_cancel if ctx else None):
            return worker(item)

    def _submit_one() -> bool:
        try:
            item = next(iterator)
        except StopIteration:
            return False
        prepared = prepare(item) if prepare else item
        pending[executor.submit(_run, prepared)] = prepared
        return True

    try:
        for _ in range(min(concurrency, len(items))):
            _submit_one()
        while pending:
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
                        f"在途 {len(pending)}，外部接口返回后继续"
                    )
                    ctx.flush()
                continue
            for future in done_futures:
                item = pending.pop(future)
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
                on_complete(completed, item, value, error, len(pending))
                if ctx:
                    ctx.check_cancel()
                _submit_one()
    except TaskCancelled:
        cancelled = sum(1 for future in pending if future.cancel())
        running = sum(1 for future in pending if not future.done() and not future.cancelled())
        if ctx:
            ctx.log(
                f"终止收尾：已取消 {cancelled} 个排队工作单元，等待 {running} 个在途请求安全结束…",
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
