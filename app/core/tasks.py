"""Shared background task registry for fire-and-forget asyncio tasks.

Tasks registered here are cancelled on app shutdown (lifespan exit) so they
don't write to a closed DB connection or leave orphan browser sessions.
"""
import asyncio

_TASKS: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    """Create a tracked background task; auto-removed from the set when done."""
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task


async def cancel_all() -> None:
    """Cancel every tracked background task and wait for them to finish."""
    for t in list(_TASKS):
        t.cancel()
    if _TASKS:
        await asyncio.gather(*_TASKS, return_exceptions=True)
