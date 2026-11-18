# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for ReconnectingMCPClient and its reconnect circuit."""

import asyncio
import inspect
import logging
import threading
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from strands.tools.mcp import MCPClient
from strands.types.exceptions import MCPClientInitializationError

from foundry_strands_agent.factory import _destination_host
from foundry_strands_agent.mcp_reconnect import (
    ReconnectingMCPClient,
    _call_connection_number,
    _is_connection_failure,
    _ReconnectCircuit,
)

_SUCCESS_RESULT = {"toolUseId": "t1", "status": "success", "content": [{"text": "ok"}]}
_ERROR_RESULT = {"toolUseId": "t1", "status": "error", "content": [{"text": "failed"}]}


def _session_terminated() -> McpError:
    return McpError(ErrorData(code=32600, message="Session terminated"))


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _make_client(**kwargs: Any) -> ReconnectingMCPClient:
    """A client with a live-looking connection and one consumer, without a real server."""
    client = ReconnectingMCPClient(MagicMock(), server_name="tools", destination_host="https://tools:8080", **kwargs)
    client._consumers = {"agent-1"}
    client._tool_provider_started = True
    return client


def _patch_connection(client: ReconnectingMCPClient, *, active: bool, start_side_effect: Any = None) -> dict[str, Any]:
    """Replace the client's connection methods with fakes and return them."""
    state = {"active": active}
    stop = MagicMock()

    def _stop(*_args: Any) -> None:
        stop()
        # Mirror the SDK: stop() clears the consumers and the started flag.
        client._consumers = set()
        client._tool_provider_started = False
        state["active"] = False

    def _start() -> ReconnectingMCPClient:
        if start_side_effect is not None:
            start_side_effect()
        state["active"] = True
        return client

    start = MagicMock(side_effect=_start)
    client.stop = MagicMock(side_effect=_stop)  # type: ignore[method-assign]
    client.start = start  # type: ignore[method-assign]
    client._is_session_active = lambda: state["active"]  # type: ignore[method-assign]
    return {"stop": stop, "start": start, "state": state}


class TestSdkPrivateMembers:
    """Fails if a strands-agents upgrade changes the private MCPClient members the reconnect relies on."""

    def test_private_members_exist(self):
        client = MCPClient(MagicMock())
        assert callable(client._is_session_active)
        assert isinstance(client._consumers, set)
        assert isinstance(client._tool_provider_started, bool)
        params = list(inspect.signature(MCPClient._handle_tool_execution_error).parameters)
        assert params == ["self", "tool_use_id", "exception"]

    def test_stop_still_clears_consumers_and_started_flag(self):
        client = MCPClient(MagicMock())
        client._consumers = {"agent-1"}
        client._tool_provider_started = True
        client.stop(None, None, None)
        assert client._consumers == set()
        assert client._tool_provider_started is False

    def test_call_tool_async_routes_sent_call_failures_to_the_error_handler(self):
        source = inspect.getsource(MCPClient.call_tool_async)
        assert "self._handle_tool_execution_error(" in source


class TestIsConnectionFailure:
    @pytest.mark.parametrize(
        "exc",
        [
            _session_terminated(),
            # Code matches but the message doesn't - still a dead connection.
            McpError(ErrorData(code=32600, message="session no longer exists")),
            # Message matches, loosely, but the code doesn't - a server or transport that
            # raises the same condition without the mcp client's own code.
            McpError(ErrorData(code=-32600, message="  SESSION TERMINATED  ")),
            RuntimeError("Connection to the MCP server was closed"),
            RuntimeError("  connection to the mcp server was closed  "),
            httpx.ConnectError("refused"),
            MCPClientInitializationError("the client session is not running"),
        ],
    )
    def test_dead_connection_errors(self, exc):
        assert _is_connection_failure(exc)

    def test_dead_connection_found_through_cause(self):
        try:
            try:
                raise httpx.ReadError("reset")
            except httpx.ReadError as inner:
                raise ValueError("wrapped") from inner
        except ValueError as outer:
            assert _is_connection_failure(outer)

    @pytest.mark.parametrize(
        "exc",
        [
            McpError(ErrorData(code=-32602, message="Invalid params")),
            RuntimeError("tool blew up"),
            ValueError("bad input"),
        ],
    )
    def test_ordinary_tool_errors(self, exc):
        assert not _is_connection_failure(exc)

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout("timed out"),
            httpx.ConnectTimeout("timed out"),
            httpx.PoolTimeout("timed out"),
            httpx.UnsupportedProtocol("unsupported protocol"),
        ],
    )
    def test_timeouts_and_unsupported_protocol_are_not_dead_connections(self, exc):
        """A slow or mis-addressed call is not a dead connection shared by every conversation."""
        assert not _is_connection_failure(exc)


class TestReconnectCircuit:
    def test_opens_after_threshold_failures(self):
        clock = _FakeClock()
        circuit = _ReconnectCircuit(threshold=3, reset_interval=60.0, clock=clock)
        assert circuit.record_failure() is False
        assert circuit.record_failure() is False
        assert circuit.record_failure() is True
        assert not circuit.allows_attempt()

    def test_allows_one_attempt_after_reset_interval(self):
        clock = _FakeClock()
        circuit = _ReconnectCircuit(threshold=1, reset_interval=60.0, clock=clock)
        circuit.record_failure()
        clock.now += 59.9
        assert not circuit.allows_attempt()
        clock.now += 0.1
        assert circuit.allows_attempt()

    def test_success_closes_and_resets_count(self):
        clock = _FakeClock()
        circuit = _ReconnectCircuit(threshold=2, reset_interval=60.0, clock=clock)
        circuit.record_failure()
        circuit.record_failure()
        clock.now += 60
        assert circuit.record_success() is True
        assert circuit.allows_attempt()
        # The count restarted, so one more failure does not reopen it.
        assert circuit.record_failure() is False

    def test_failure_after_reset_interval_reopens(self):
        clock = _FakeClock()
        circuit = _ReconnectCircuit(threshold=1, reset_interval=60.0, clock=clock)
        circuit.record_failure()
        clock.now += 60
        assert circuit.allows_attempt()
        assert circuit.record_failure() is True
        assert not circuit.allows_attempt()


class TestReconnectBeforeCall:
    @pytest.mark.asyncio
    async def test_healthy_client_does_not_reconnect(self):
        client = _make_client()
        fakes = _patch_connection(client, active=True)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)) as sent:
            result = await client.call_tool_async("t1", "echo", {"text": "hi"})
        assert result == _SUCCESS_RESULT
        fakes["start"].assert_not_called()
        sent.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connection_not_running_reconnects_then_sends(self):
        client = _make_client()
        fakes = _patch_connection(client, active=False)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)) as sent:
            result = await client.call_tool_async("t1", "echo", {"text": "hi"})
        assert result == _SUCCESS_RESULT
        fakes["stop"].assert_called_once()
        fakes["start"].assert_called_once()
        sent.assert_awaited_once_with("t1", "echo", {"text": "hi"})

    @pytest.mark.asyncio
    async def test_reconnect_keeps_consumers_and_started_flag(self):
        client = _make_client()
        client._consumers = {"agent-1", "agent-2"}
        _patch_connection(client, active=False)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            await client.call_tool_async("t1", "echo", {})
        assert client._consumers == {"agent-1", "agent-2"}
        assert client._tool_provider_started is True

    @pytest.mark.asyncio
    async def test_stop_close_error_is_ignored(self):
        client = _make_client()
        fakes = _patch_connection(client, active=False)
        fakes["stop"].side_effect = RuntimeError("Connection to the MCP server was closed")
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            result = await client.call_tool_async("t1", "echo", {})
        assert result == _SUCCESS_RESULT
        fakes["start"].assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_reconnect_raises_and_keeps_consumers(self):
        client = _make_client()

        def _refuse() -> None:
            raise ConnectionError("refused")

        _patch_connection(client, active=False, start_side_effect=_refuse)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)) as sent:
            with pytest.raises(MCPClientInitializationError, match="MCP reconnect failed"):
                await client.call_tool_async("t1", "echo", {})
        sent.assert_not_awaited()
        assert client._consumers == {"agent-1"}
        # start() never succeeded, so the flag must not claim it did - otherwise the
        # next load_tools() would skip retrying start() against a dead session.
        assert client._tool_provider_started is False

    @pytest.mark.asyncio
    async def test_client_without_consumers_is_not_reconnected(self):
        client = _make_client()
        client._consumers = set()
        fakes = _patch_connection(client, active=False)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            await client.call_tool_async("t1", "echo", {})
        fakes["start"].assert_not_called()


class TestFailureAfterSend:
    @pytest.mark.asyncio
    async def test_dead_connection_error_marks_stale_without_resending(self):
        client = _make_client()
        fakes = _patch_connection(client, active=True)

        async def _fails_after_send(*_args: Any, **_kwargs: Any) -> Any:
            return client._handle_tool_execution_error("t1", _session_terminated())

        with patch.object(MCPClient, "call_tool_async", AsyncMock(side_effect=_fails_after_send)) as sent:
            result = await client.call_tool_async("t1", "create_ticket", {})
        assert result["status"] == "error"
        sent.assert_awaited_once()
        fakes["start"].assert_not_called()
        assert client._reconnect_stale is True

    @pytest.mark.asyncio
    async def test_next_call_reconnects_after_dead_connection_error(self):
        client = _make_client()
        fakes = _patch_connection(client, active=True)
        client._handle_tool_execution_error("t1", _session_terminated())
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            result = await client.call_tool_async("t2", "echo", {})
        assert result == _SUCCESS_RESULT
        fakes["start"].assert_called_once()
        assert client._reconnect_stale is False

    def test_ordinary_tool_error_does_not_mark_stale(self):
        client = _make_client()
        result = client._handle_tool_execution_error("t1", ValueError("bad input"))
        assert result["status"] == "error"
        assert client._reconnect_stale is False

    @pytest.mark.asyncio
    async def test_read_timeout_does_not_tear_down_the_shared_client(self):
        """A ReadTimeout is that call's error. The next call stays on the same connection."""
        client = _make_client()
        fakes = _patch_connection(client, active=True)

        async def _times_out(tool_use_id: str, *_args: Any, **_kwargs: Any) -> Any:
            return client._handle_tool_execution_error(tool_use_id, httpx.ReadTimeout("timed out"))

        with patch.object(MCPClient, "call_tool_async", AsyncMock(side_effect=_times_out)):
            result = await client.call_tool_async("t1", "echo", {})
        assert result["status"] == "error"
        assert client._reconnect_stale is False

        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            assert await client.call_tool_async("t2", "echo", {}) == _SUCCESS_RESULT
        fakes["start"].assert_not_called()


class TestLoadToolsAfterFailedReconnect:
    @pytest.mark.asyncio
    async def test_load_tools_recovers_after_a_failed_reconnect(self):
        """load_tools() must recover once the server is back.

        Expected: once a prior reconnect attempt failed and the server is reachable again,
        load_tools() retries start() and succeeds. Currently fails: the buggy _reconnect()
        restores _tool_provider_started=True on a failed attempt even though start() never
        succeeded, so load_tools() trusts that flag, never retries start(), and keeps
        raising "client session is not running" forever instead of recovering.
        """
        client = _make_client()
        attempts = {"count": 0}

        def _refuse_once() -> None:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ConnectionError("refused")

        fakes = _patch_connection(client, active=False, start_side_effect=_refuse_once)

        def _fake_list_all_tools_sync() -> list[str]:
            if not client._is_session_active():
                raise MCPClientInitializationError("the client session is not running")
            return ["tool-a"]

        client._list_all_tools_sync = _fake_list_all_tools_sync  # type: ignore[method-assign]

        with pytest.raises(MCPClientInitializationError, match="MCP reconnect failed"):
            client._reconnect()

        # The server would accept a second start() attempt now (attempts["count"] == 1,
        # so the next call succeeds).
        assert await client.load_tools() == ["tool-a"]
        assert fakes["start"].call_count == 2

    @pytest.mark.asyncio
    async def test_load_tools_after_failed_then_successful_reconnect(self):
        """load_tools() must use the session a later successful reconnect already started.

        A failed attempt leaves _tool_provider_started False. The next attempt that
        succeeds must set it back to True. Otherwise load_tools() sees False, calls
        start() on the live session, and the SDK raises "the client session is currently running".
        """
        client = _make_client()
        attempts = {"count": 0}
        state = {"active": False}

        def _start() -> ReconnectingMCPClient:
            # Mirror MCPClient.start(): a session that is already up is not started again.
            if state["active"]:
                raise MCPClientInitializationError("the client session is currently running")
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ConnectionError("refused")
            state["active"] = True
            return client

        def _stop(*_args: Any) -> None:
            client._consumers = set()
            client._tool_provider_started = False
            state["active"] = False

        client.stop = MagicMock(side_effect=_stop)  # type: ignore[method-assign]
        client.start = MagicMock(side_effect=_start)  # type: ignore[method-assign]
        client._is_session_active = lambda: state["active"]  # type: ignore[method-assign]

        def _fake_list_all_tools_sync() -> list[str]:
            if not client._is_session_active():
                raise MCPClientInitializationError("the client session is not running")
            return ["tool-a"]

        client._list_all_tools_sync = _fake_list_all_tools_sync  # type: ignore[method-assign]

        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            with pytest.raises(MCPClientInitializationError, match="MCP reconnect failed"):
                await client.call_tool_async("t1", "echo", {})
            assert await client.call_tool_async("t2", "echo", {}) == _SUCCESS_RESULT

        assert client._tool_provider_started is True
        assert await client.load_tools() == ["tool-a"]
        # One failed start and one successful reconnect. load_tools() must not start again.
        assert client.start.call_count == 2


class TestLoadToolsCancellation:
    @pytest.mark.asyncio
    async def test_cancelling_load_tools_during_reconnect_does_not_wedge_the_lock(self):
        """Cancelling load_tools() must not strand _reconnect_lock.

        Expected: once the in-flight reconnect finishes, the lock is available again,
        regardless of whether some earlier load_tools() call was cancelled while waiting
        on it. Currently fails: load_tools() waits out a reconnect on a worker thread
        (asyncio.to_thread(self._reconnect_lock.acquire)) and releases it on the very next
        line. Cancelling that wait does not stop the worker thread - it still acquires the
        lock once the reconnect releases it - but the coroutine already exited via
        CancelledError before reaching that release(), so the lock is held forever.
        """
        client = _make_client()
        reconnect_holds_lock = threading.Event()
        release_reconnect = threading.Event()

        def _slow_start() -> None:
            reconnect_holds_lock.set()
            assert release_reconnect.wait(timeout=2)

        _patch_connection(client, active=False, start_side_effect=_slow_start)

        reconnect_thread = threading.Thread(target=client._reconnect)
        reconnect_thread.start()
        assert reconnect_holds_lock.wait(timeout=2)
        assert client._reconnect_lock.locked()

        load_tools_task = asyncio.create_task(client.load_tools())
        # Give the task's asyncio.to_thread() worker time to start blocking on acquire().
        await asyncio.sleep(0.1)
        load_tools_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await load_tools_task

        # The reconnect finishes and releases the lock...
        release_reconnect.set()
        reconnect_thread.join(timeout=2)
        assert not reconnect_thread.is_alive()

        # ...give the cancelled load_tools()'s background thread time to run to completion,
        # however it handles the lock.
        await asyncio.sleep(0.3)

        # Expected: the lock is available again, not stuck held forever.
        acquired = client._reconnect_lock.acquire(blocking=False)
        try:
            assert acquired, "cancelling load_tools() during a reconnect left _reconnect_lock stuck held"
        finally:
            if acquired:
                client._reconnect_lock.release()


class TestConcurrentReconnect:
    @pytest.mark.asyncio
    async def test_concurrent_calls_share_one_reconnect(self):
        client = _make_client()
        # Slow enough that every call is waiting on the lock while the first reconnects.
        fakes = _patch_connection(client, active=False, start_side_effect=lambda: time.sleep(0.2))
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)) as sent:
            results = await asyncio.gather(*(client.call_tool_async(f"t{i}", "echo", {}) for i in range(5)))
        assert results == [_SUCCESS_RESULT] * 5
        fakes["start"].assert_called_once()
        assert sent.await_count == 5

    @pytest.mark.asyncio
    async def test_concurrent_calls_share_one_failed_reconnect(self):
        client = _make_client()

        def _slow_refuse() -> None:
            time.sleep(0.2)
            raise ConnectionError("refused")

        fakes = _patch_connection(client, active=False, start_side_effect=_slow_refuse)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)) as sent:
            results = await asyncio.gather(
                *(client.call_tool_async(f"t{i}", "echo", {}) for i in range(5)), return_exceptions=True
            )
        assert all(isinstance(r, MCPClientInitializationError) for r in results), results
        assert all("MCP reconnect failed" in str(r) for r in results)
        fakes["start"].assert_called_once()
        sent.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_later_call_after_failed_reconnect_tries_again(self):
        client = _make_client()
        attempts = {"count": 0}

        def _refuse_first() -> None:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ConnectionError("refused")

        fakes = _patch_connection(client, active=False, start_side_effect=_refuse_first)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            with pytest.raises(MCPClientInitializationError):
                await client.call_tool_async("t1", "echo", {})
            assert await client.call_tool_async("t2", "echo", {}) == _SUCCESS_RESULT
        assert fakes["start"].call_count == 2

    def test_reconnect_holds_a_thread_lock(self):
        client = _make_client()
        assert isinstance(client._reconnect_lock, type(threading.Lock()))


class TestLoadToolsDuringReconnect:
    @pytest.mark.asyncio
    async def test_load_tools_waits_for_in_flight_reconnect(self):
        """P2: load_tools() must not see _tool_provider_started restored before start() finishes."""
        client = _make_client()
        state = {"start_finished": False}

        def _slow_start() -> None:
            time.sleep(0.2)
            state["start_finished"] = True

        _patch_connection(client, active=False, start_side_effect=_slow_start)
        observed: dict[str, bool] = {}

        async def _load_tools(**_kwargs: Any) -> list[str]:
            observed["start_finished_when_loaded"] = state["start_finished"]
            return ["tool-a"]

        reconnect_thread = threading.Thread(target=client._reconnect)
        reconnect_thread.start()
        while not client._reconnect_lock.locked():
            await asyncio.sleep(0.01)

        with patch.object(MCPClient, "load_tools", AsyncMock(side_effect=_load_tools)):
            result = await client.load_tools()
        reconnect_thread.join()

        assert result == ["tool-a"]
        assert observed["start_finished_when_loaded"] is True


class TestConsumerChangesDuringReconnect:
    def test_remove_consumer_during_reconnect_is_not_resurrected(self):
        """P3: a consumer removed while reconnect is stopping must not come back from its snapshot."""
        client = _make_client()
        client.add_consumer("agent-2")  # _consumers == {"agent-1", "agent-2"}

        stop_entered = threading.Event()
        release_stop = threading.Event()

        def _stop(*_args: Any) -> None:
            stop_entered.set()
            release_stop.wait(timeout=2)
            client._consumers = set()
            client._tool_provider_started = False

        client.stop = MagicMock(side_effect=_stop)  # type: ignore[method-assign]
        client.start = MagicMock(return_value=client)  # type: ignore[method-assign]
        client._is_session_active = lambda: False  # type: ignore[method-assign]

        reconnect_thread = threading.Thread(target=client._reconnect)
        reconnect_thread.start()
        assert stop_entered.wait(timeout=2)

        # While reconnect is paused inside stop(), still holding the pre-stop snapshot,
        # try to remove a consumer. Without the fix this races the snapshot/restore and
        # the removal is undone; with it, this blocks until reconnect is done.
        remove_thread = threading.Thread(target=client.remove_consumer, args=("agent-2",))
        remove_thread.start()
        time.sleep(0.05)

        release_stop.set()
        reconnect_thread.join()
        remove_thread.join()

        assert client._consumers == {"agent-1"}


class TestConsumerChangesDoNotBlockDuringReconnect:
    """add_consumer()/remove_consumer() must not block on a reconnect.

    The SDK documents both as synchronous "to prevent GC deadlocks when called from Agent
    finalizers" (Agent.__del__ -> ToolRegistry.cleanup() -> remove_consumer). Blocking them
    on the same threading.Lock a reconnect holds for its whole duration means a finalizer
    firing on the event loop thread during a reconnect freezes the loop for as long as the
    reconnect takes - up to the SDK's startup_timeout (default 30s) on a failing one.
    """

    def _start_slow_reconnect(self, client: ReconnectingMCPClient) -> tuple[threading.Thread, threading.Event]:
        reconnect_holds_lock = threading.Event()
        release_reconnect = threading.Event()

        def _slow_start() -> None:
            reconnect_holds_lock.set()
            assert release_reconnect.wait(timeout=2)

        _patch_connection(client, active=False, start_side_effect=_slow_start)

        reconnect_thread = threading.Thread(target=client._reconnect)
        reconnect_thread.start()
        assert reconnect_holds_lock.wait(timeout=2)
        assert client._reconnect_lock.locked()
        return reconnect_thread, release_reconnect

    def test_remove_consumer_does_not_block_while_reconnect_is_in_progress(self):
        client = _make_client()
        client.add_consumer("agent-2")  # _consumers == {"agent-1", "agent-2"}
        reconnect_thread, release_reconnect = self._start_slow_reconnect(client)

        call_finished = threading.Event()
        call_thread = threading.Thread(target=lambda: (client.remove_consumer("agent-2"), call_finished.set()))
        start = time.monotonic()
        call_thread.start()

        # Expected: remove_consumer() returns quickly - it must not wait out the reconnect.
        returned_promptly = call_finished.wait(timeout=0.3)
        elapsed = time.monotonic() - start

        release_reconnect.set()
        reconnect_thread.join(timeout=2)
        call_thread.join(timeout=2)

        assert returned_promptly, "remove_consumer() blocked on the in-flight reconnect"
        assert elapsed < 0.3

    def test_add_consumer_does_not_block_while_reconnect_is_in_progress(self):
        client = _make_client()
        reconnect_thread, release_reconnect = self._start_slow_reconnect(client)

        call_finished = threading.Event()
        call_thread = threading.Thread(target=lambda: (client.add_consumer("agent-2"), call_finished.set()))
        start = time.monotonic()
        call_thread.start()

        # Expected: add_consumer() returns quickly - it must not wait out the reconnect.
        returned_promptly = call_finished.wait(timeout=0.3)
        elapsed = time.monotonic() - start

        release_reconnect.set()
        reconnect_thread.join(timeout=2)
        call_thread.join(timeout=2)

        assert returned_promptly, "add_consumer() blocked on the in-flight reconnect"
        assert elapsed < 0.3

    def test_queued_removal_is_applied_when_reconnect_finishes_before_it_is_queued(self):
        """A removal queued just after the reconnect drained and released the lock is still applied."""
        client = _make_client()
        client.add_consumer("agent-2")  # _consumers == {"agent-1", "agent-2"}
        reconnect_thread, release_reconnect = self._start_slow_reconnect(client)
        real_pending_lock = client._pending_lock
        caller = threading.current_thread()

        class _FinishReconnectBeforeQueuing:
            """Lets the whole reconnect finish in the gap after the caller's failed acquire."""

            fired = False

            def __enter__(self) -> None:
                if threading.current_thread() is caller and not self.fired:
                    self.fired = True
                    release_reconnect.set()
                    reconnect_thread.join(timeout=2)
                real_pending_lock.acquire()

            def __exit__(self, *_args: Any) -> None:
                real_pending_lock.release()

        client._pending_lock = _FinishReconnectBeforeQueuing()  # type: ignore[assignment]
        client.remove_consumer("agent-2")

        assert not reconnect_thread.is_alive()
        assert client._consumers == {"agent-1"}
        assert client._pending_consumer_ops == []
        assert not client._reconnect_lock.locked()

    def test_failing_queued_change_does_not_replace_the_reconnect_error(self):
        """A queued change that raises while a failed reconnect drains must not hide its error."""
        client = _make_client()
        client.add_consumer("agent-2")
        reconnect_holds_lock = threading.Event()
        release_reconnect = threading.Event()

        def _slow_refuse() -> None:
            reconnect_holds_lock.set()
            assert release_reconnect.wait(timeout=2)
            raise ConnectionError("refused")

        _patch_connection(client, active=False, start_side_effect=_slow_refuse)
        raised: list[BaseException] = []

        def _run_reconnect() -> None:
            try:
                client._reconnect()
            except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
                raised.append(exc)

        reconnect_thread = threading.Thread(target=_run_reconnect)
        reconnect_thread.start()
        assert reconnect_holds_lock.wait(timeout=2)

        with patch.object(MCPClient, "remove_consumer", MagicMock(side_effect=RuntimeError("stop failed"))):
            client.remove_consumer("agent-2")  # queued: the reconnect holds the lock
            release_reconnect.set()
            reconnect_thread.join(timeout=2)

        assert len(raised) == 1
        assert isinstance(raised[0], MCPClientInitializationError)
        assert "MCP reconnect failed" in str(raised[0])


class TestConnectionNumber:
    @pytest.mark.asyncio
    async def test_late_error_from_replaced_connection_does_not_reconnect_again(self):
        client = _make_client()
        fakes = _patch_connection(client, active=True)
        release_old_call = asyncio.Event()

        async def _send(tool_use_id: str, *_args: Any, **_kwargs: Any) -> Any:
            if tool_use_id == "old":
                # In flight on connection 1 while the client reconnects to connection 2.
                await release_old_call.wait()
                return client._handle_tool_execution_error(tool_use_id, _session_terminated())
            return _SUCCESS_RESULT

        with patch.object(MCPClient, "call_tool_async", AsyncMock(side_effect=_send)):
            old_call = asyncio.create_task(client.call_tool_async("old", "echo", {}))
            await asyncio.sleep(0)
            client._handle_tool_execution_error("first", _session_terminated())
            assert await client.call_tool_async("new", "echo", {}) == _SUCCESS_RESULT
            assert client._connection_number == 2

            release_old_call.set()
            assert (await old_call)["status"] == "error"
            assert client._reconnect_stale is False
            assert await client.call_tool_async("next", "echo", {}) == _SUCCESS_RESULT
        fakes["start"].assert_called_once()

    @pytest.mark.asyncio
    async def test_late_error_while_stale_is_cleared_does_not_mark_the_new_connection(self):
        """An error from the connection being replaced must not mark the new one stale."""
        client = _make_client()
        fakes = _patch_connection(client, active=False)
        sent_on = client._connection_number
        delivered = {"done": False}

        class _DeliverLateErrorOnClear:
            """Runs the old connection's error in the gap after the stale flag is cleared."""

            def __get__(self, obj: Any, objtype: type | None = None) -> Any:
                if obj is None:
                    return self
                return obj.__dict__["_reconnect_stale"]

            def __set__(self, obj: Any, value: bool) -> None:
                obj.__dict__["_reconnect_stale"] = value
                if value is False and obj is client and not delivered["done"]:
                    delivered["done"] = True
                    token = _call_connection_number.set(sent_on)
                    try:
                        obj._handle_tool_execution_error("old", _session_terminated())
                    finally:
                        _call_connection_number.reset(token)

        ReconnectingMCPClient._reconnect_stale = _DeliverLateErrorOnClear()  # type: ignore[assignment]
        try:
            with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
                assert await client.call_tool_async("t1", "echo", {}) == _SUCCESS_RESULT
                assert delivered["done"] is True
                assert await client.call_tool_async("t2", "echo", {}) == _SUCCESS_RESULT
            assert fakes["start"].call_count == 1, "late error from the old connection marked the new one stale"
        finally:
            del ReconnectingMCPClient._reconnect_stale

    @pytest.mark.asyncio
    async def test_error_on_current_connection_after_a_reconnect_still_reconnects(self):
        client = _make_client()
        fakes = _patch_connection(client, active=False)

        async def _fails_after_send(tool_use_id: str, *_args: Any, **_kwargs: Any) -> Any:
            return client._handle_tool_execution_error(tool_use_id, _session_terminated())

        with patch.object(MCPClient, "call_tool_async", AsyncMock(side_effect=_fails_after_send)):
            await client.call_tool_async("t1", "echo", {})
        assert client._connection_number == 2
        assert client._reconnect_stale is True
        fakes["start"].assert_called_once()


class TestConnectionLifetime:
    @pytest.mark.asyncio
    async def test_connection_closes_when_last_agent_is_released_after_a_reconnect(self):
        client = _make_client()
        client._consumers = {"agent-1", "agent-2"}
        fakes = _patch_connection(client, active=False)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            await client.call_tool_async("t1", "echo", {})
        stops_after_reconnect = fakes["stop"].call_count

        client.remove_consumer("agent-1")
        assert fakes["stop"].call_count == stops_after_reconnect
        client.remove_consumer("agent-2")
        assert fakes["stop"].call_count == stops_after_reconnect + 1

    @pytest.mark.asyncio
    async def test_stale_flag_does_not_outlive_the_stopped_client(self):
        """After the last agent leaves, the next agent's first call uses its new session."""
        client = _make_client()
        fakes = _patch_connection(client, active=True)
        client._handle_tool_execution_error("t1", _session_terminated())
        assert client._reconnect_stale is True

        client.remove_consumer("agent-1")
        assert client._consumers == set()
        fakes["stop"].assert_called_once()

        client.add_consumer("agent-2")
        client._list_all_tools_sync = lambda: ["tool-a"]  # type: ignore[method-assign]
        assert await client.load_tools() == ["tool-a"]
        assert fakes["start"].call_count == 1
        assert client._is_session_active()

        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            assert await client.call_tool_async("t2", "echo", {}) == _SUCCESS_RESULT
        assert fakes["start"].call_count == 1, (
            "stale flag survived stop() and the first call tore the fresh session down"
        )


class TestCircuitOnClient:
    @pytest.mark.asyncio
    async def test_open_circuit_fails_fast_without_connecting(self):
        client = _make_client(circuit_threshold=2, circuit_reset_interval=60.0)

        def _refuse() -> None:
            raise ConnectionError("refused")

        fakes = _patch_connection(client, active=False, start_side_effect=_refuse)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            for _ in range(2):
                with pytest.raises(MCPClientInitializationError, match="reconnect failed"):
                    await client.call_tool_async("t1", "echo", {})
            with pytest.raises(MCPClientInitializationError, match="circuit is open"):
                await client.call_tool_async("t1", "echo", {})
        assert fakes["start"].call_count == 2

    @pytest.mark.asyncio
    async def test_circuit_closes_after_reset_interval_and_success(self):
        client = _make_client(circuit_threshold=1, circuit_reset_interval=60.0)
        clock = _FakeClock()
        client._reconnect_circuit._clock = clock
        attempts = {"count": 0}

        def _refuse_first() -> None:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ConnectionError("refused")

        _patch_connection(client, active=False, start_side_effect=_refuse_first)
        with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
            with pytest.raises(MCPClientInitializationError):
                await client.call_tool_async("t1", "echo", {})
            clock.now += 60
            assert await client.call_tool_async("t1", "echo", {}) == _SUCCESS_RESULT
        assert client._reconnect_circuit.allows_attempt()


class TestReconnectLogging:
    @pytest.mark.asyncio
    async def test_logs_server_and_host_without_credentials(self, caplog):
        secret_url = "https://user:super-secret@tools.example.com:8443/mcp?token=also-secret"  # trufflehog:ignore
        client = ReconnectingMCPClient(MagicMock(), server_name="tools", destination_host=_destination_host(secret_url))
        client._consumers = {"agent-1"}
        client._tool_provider_started = True
        _patch_connection(client, active=False)
        with caplog.at_level(logging.INFO, logger="foundry_strands_agent.mcp_reconnect"):
            with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
                await client.call_tool_async("t1", "echo", {})
        records = [r for r in caplog.records if r.name == "foundry_strands_agent.mcp_reconnect"]
        assert [r.getMessage() for r in records] == ["Reconnecting MCP client", "MCP client reconnected"]
        for record in records:
            assert record.__dict__["server_name"] == "tools"
            assert record.__dict__["destination_host"] == "https://tools.example.com:8443"
            assert "secret" not in str(record.__dict__)

    @pytest.mark.asyncio
    async def test_failure_and_circuit_logs_have_no_credentials(self, caplog):
        secret_url = "https://user:super-secret@tools.example.com:8443/mcp?token=also-secret"  # trufflehog:ignore
        client = ReconnectingMCPClient(
            MagicMock(), server_name="tools", destination_host=_destination_host(secret_url), circuit_threshold=1
        )
        client._consumers = {"agent-1"}
        client._tool_provider_started = True

        def _refuse() -> None:
            raise ConnectionError(f"refused {secret_url}")

        _patch_connection(client, active=False, start_side_effect=_refuse)
        with caplog.at_level(logging.INFO, logger="foundry_strands_agent.mcp_reconnect"):
            with patch.object(MCPClient, "call_tool_async", AsyncMock(return_value=_SUCCESS_RESULT)):
                with pytest.raises(MCPClientInitializationError):
                    await client.call_tool_async("t1", "echo", {})
        records = [r for r in caplog.records if r.name == "foundry_strands_agent.mcp_reconnect"]
        messages = [r.getMessage() for r in records]
        assert "MCP reconnect failed" in messages
        assert "MCP reconnect circuit opened" in messages
        for record in records:
            assert "secret" not in record.getMessage()
            assert "secret" not in str(record.__dict__)
