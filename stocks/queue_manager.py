"""
queue_manager.py — FIFO queue with rate limiting for SMB Algo Stocks

Each account has its own independent queue.
Rate limit: MAX_CALLS_PER_MINUTE across all queues combined.
"""
import asyncio
import logging
import time
from collections import deque
from datetime import datetime
from typing import Callable, Any

logger = logging.getLogger(__name__)

MAX_CALLS_PER_MINUTE = 90
CALL_INTERVAL = 60.0 / MAX_CALLS_PER_MINUTE  # seconds between calls

# Track API call timestamps for rate limiting
_call_timestamps: deque = deque()

# Per-account queues: {account_id: asyncio.Queue}
_queues: dict[int, asyncio.Queue] = {}

# Per-account queue processing tasks
_queue_tasks: dict[int, asyncio.Task] = {}


def get_queue(account_id: int) -> asyncio.Queue:
    """Get or create the queue for an account."""
    if account_id not in _queues:
        _queues[account_id] = asyncio.Queue()
    return _queues[account_id]


async def rate_limit_wait():
    """
    Wait if needed to stay within MAX_CALLS_PER_MINUTE.
    Tracks a rolling 60-second window of API calls.
    """
    now = time.monotonic()

    # Remove timestamps older than 60 seconds
    while _call_timestamps and now - _call_timestamps[0] > 60.0:
        _call_timestamps.popleft()

    if len(_call_timestamps) >= MAX_CALLS_PER_MINUTE:
        # Need to wait until the oldest call falls out of the 60s window
        wait_time = 60.0 - (now - _call_timestamps[0]) + 0.1
        if wait_time > 0:
            logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)

    _call_timestamps.append(time.monotonic())


async def enqueue(account_id: int, task_fn: Callable, *args, **kwargs):
    """
    Add a task to an account's queue.
    task_fn will be called with the given args when processed.
    """
    queue = get_queue(account_id)
    await queue.put((task_fn, args, kwargs))
    logger.info(f"[Account {account_id}] Task enqueued. Queue size: {queue.qsize()}")

    # Start queue processor if not already running
    if account_id not in _queue_tasks or _queue_tasks[account_id].done():
        _queue_tasks[account_id] = asyncio.create_task(
            _process_queue(account_id)
        )


async def _process_queue(account_id: int):
    """
    Process tasks from an account's queue sequentially with rate limiting.
    Runs until the queue is empty.
    """
    queue = get_queue(account_id)
    logger.info(f"[Account {account_id}] Queue processor started")
    await asyncio.sleep(account_id * 0.25)

    while not queue.empty():
        task_fn, args, kwargs = await queue.get()
        try:
            await rate_limit_wait()
            if asyncio.iscoroutinefunction(task_fn):
                await task_fn(*args, **kwargs)
            else:
                task_fn(*args, **kwargs)
        except Exception as e:
            logger.error(f"[Account {account_id}] Queue task failed: {e}")
        finally:
            queue.task_done()

    logger.info(f"[Account {account_id}] Queue processor finished")


async def clear_queue(account_id: int):
    """Clear all pending tasks for an account (used on kill/loss limit breach)."""
    queue = get_queue(account_id)
    cleared = 0
    while not queue.empty():
        try:
            queue.get_nowait()
            queue.task_done()
            cleared += 1
        except asyncio.QueueEmpty:
            break
    logger.info(f"[Account {account_id}] Queue cleared: {cleared} tasks removed")
    return cleared


def queue_status() -> dict:
    """Return current queue sizes for all accounts."""
    return {
        acc_id: queue.qsize()
        for acc_id, queue in _queues.items()
    }
