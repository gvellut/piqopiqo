"""Tests for metadata save worker shutdown helpers."""

from __future__ import annotations

from piqopiqo.metadata.save_workers import drain_qthread_pool


class _StubThreadPool:
    def __init__(self, wait_result: bool):
        self.wait_result = wait_result
        self.calls: list[tuple[str, int | None]] = []

    def clear(self) -> None:
        self.calls.append(("clear", None))

    def waitForDone(self, timeout_ms: int) -> bool:
        self.calls.append(("waitForDone", timeout_ms))
        return self.wait_result


def test_drain_qthread_pool_clears_queue_before_wait():
    pool = _StubThreadPool(wait_result=False)

    result = drain_qthread_pool(pool, 1234)

    assert result is False
    assert pool.calls == [("clear", None), ("waitForDone", 1234)]


def test_drain_qthread_pool_can_skip_clear():
    pool = _StubThreadPool(wait_result=True)

    result = drain_qthread_pool(pool, 99, clear_queued=False)

    assert result is True
    assert pool.calls == [("waitForDone", 99)]
