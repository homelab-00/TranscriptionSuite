"""Tests for API client aiohttp session loop affinity handling."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("aiohttp")

from dashboard.common.api_client import APIClient


class _DummyConnector:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _DummySession:
    instances: list["_DummySession"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.closed = False
        _DummySession.instances.append(self)

    async def close(self) -> None:
        self.closed = True


def test_get_session_reuses_session_within_same_event_loop(monkeypatch) -> None:
    _DummySession.instances.clear()
    monkeypatch.setattr(
        "dashboard.common.api_client.aiohttp.TCPConnector",
        _DummyConnector,
    )
    monkeypatch.setattr(
        "dashboard.common.api_client.aiohttp.ClientSession",
        _DummySession,
    )

    client = APIClient()

    async def _run() -> tuple[_DummySession, _DummySession]:
        first = await client._get_session()
        second = await client._get_session()
        return first, second

    first, second = asyncio.run(_run())
    assert first is second
    assert len(_DummySession.instances) == 1

    asyncio.run(client.close())


def test_get_session_recreates_session_when_event_loop_changes(monkeypatch) -> None:
    _DummySession.instances.clear()
    monkeypatch.setattr(
        "dashboard.common.api_client.aiohttp.TCPConnector",
        _DummyConnector,
    )
    monkeypatch.setattr(
        "dashboard.common.api_client.aiohttp.ClientSession",
        _DummySession,
    )

    client = APIClient()

    first = asyncio.run(client._get_session())
    second = asyncio.run(client._get_session())

    assert first is not second
    assert first.closed is True
    assert len(_DummySession.instances) == 2

    asyncio.run(client.close())
