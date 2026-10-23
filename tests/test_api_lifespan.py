import asyncio

from crew import api


def test_application_lifespan_starts_and_stops_services(monkeypatch):
    calls = []

    async def fake_boot():
        calls.append("boot")

    async def fake_shutdown():
        calls.append("shutdown")

    monkeypatch.setattr(api, "boot", fake_boot)
    monkeypatch.setattr(api, "shutdown", fake_shutdown)

    async def exercise_lifespan():
        async with api.lifespan(api.app):
            calls.append("serving")

    asyncio.run(exercise_lifespan())

    assert calls == ["boot", "serving", "shutdown"]


def test_application_lifespan_releases_services_if_startup_raises(monkeypatch):
    calls = []

    async def failed_boot():
        calls.append("boot")
        raise RuntimeError("startup failed")

    async def fake_shutdown():
        calls.append("shutdown")

    monkeypatch.setattr(api, "boot", failed_boot)
    monkeypatch.setattr(api, "shutdown", fake_shutdown)

    async def exercise_lifespan():
        async with api.lifespan(api.app):
            pass

    try:
        asyncio.run(exercise_lifespan())
    except RuntimeError as exc:
        assert str(exc) == "startup failed"
    else:
        raise AssertionError("startup failure should propagate")

    assert calls == ["boot", "shutdown"]
