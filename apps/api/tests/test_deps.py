import threading
import time

import pytest
from fastapi import Request

import pigrocrm_api.deps as deps
from pigrocrm.core.config import Settings


def test_get_session_builds_the_engine_exactly_once_under_concurrent_cold_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FastAPI runs sync dependencies in a thread pool: several requests can reach
    get_session()'s cold-start check before the first one finishes building the
    engine. A naive check-then-act on the module globals would let each of them build
    (and leak) its own Engine, and could even leave `_factory` bound to a different
    Engine than the one `_engine` ends up holding.

    This drives many threads through that window at once. `create_engine_from_settings`
    is wrapped with an artificial delay and does not touch a real database -- creating
    a SQLAlchemy Engine never connects eagerly -- so the race is exercised
    deterministically: the delay only widens a window that already exists, it does not
    manufacture one that would not otherwise be there.
    """
    monkeypatch.setattr(deps, "_engine", None)
    monkeypatch.setattr(deps, "_factory", None)

    calls = 0
    calls_lock = threading.Lock()
    real_create_engine_from_settings = deps.create_engine_from_settings

    def slow_create_engine_from_settings(settings: object) -> object:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return real_create_engine_from_settings(settings)  # type: ignore[arg-type]

    monkeypatch.setattr(deps, "create_engine_from_settings", slow_create_engine_from_settings)

    thread_count = 8
    barrier = threading.Barrier(thread_count)
    errors: list[BaseException] = []

    # A root request: no space prefix, so `get_session` takes the shared root engine.
    request = Request({"type": "http", "path": "/api/customers", "headers": [], "state": {}})
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    def worker() -> None:
        barrier.wait()
        try:
            generator = deps.get_session(request, settings)
            next(generator)
            generator.close()
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors`, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert calls == 1, f"expected exactly one Engine to be built, got {calls}"
