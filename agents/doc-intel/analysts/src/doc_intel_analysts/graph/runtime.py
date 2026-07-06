"""Lazy cognee runtime with an explicit release for the embedded Kuzu handle.

Embedded Kuzu is single-writer and the lock is held per process: a service
that has lazily initialized cognee holds the store open even when idle, which
blocks the ingest CLI (a separate process). `release()` exists so the service
can drop the handle; operationally, stage 1 stops the service during ingest
and restarts it after (see the plan's Risks — this is the belt to that
suspenders).
"""

from . import config

_initialized = False


def get_cognee():
    """Configure env (guarded), then import and return the cognee module."""
    global _initialized
    if not _initialized:
        config.configure()
        _initialized = True
    import cognee  # deferred: env must be set before first import

    return cognee


async def release() -> None:
    """Best-effort release of embedded store handles (Kuzu single-writer)."""
    global _initialized
    if not _initialized:
        return
    try:
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        close = getattr(engine, "close", None) or getattr(engine, "disconnect", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
    except Exception:
        # Release is best-effort; the hard rule is service-stopped-during-ingest.
        pass
    _initialized = False
