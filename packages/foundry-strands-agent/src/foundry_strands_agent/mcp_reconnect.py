# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""MCP client that reconnects a broken MCP connection in place.

Every agent built from one ``AgentBuilder`` shares the same MCP client objects,
and each MCP tool calls through its client. A client that reconnects itself
therefore restores the tools of every agent holding it, without rebuilding any
agent. The strands SDK only reconnects a client once the last agent holding it
is released, which rarely happens when many conversations are cached.

A call that fails after it was sent is never re-sent, because the server may
already have run the tool. Only the next call reconnects.

This relies on private ``MCPClient`` members (``_is_session_active``,
``_consumers``, ``_tool_provider_started``, ``_handle_tool_execution_error``).
``tests/unit/test_mcp_reconnect.py`` fails if they change.
"""

import asyncio
import contextvars
import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, override

import httpx
from mcp.shared.exceptions import McpError
from strands.tools.mcp import MCPClient
from strands.tools.mcp.mcp_types import MCPToolResult
from strands.types.exceptions import MCPClientInitializationError
from strands.types.tools import AgentTool

logger = logging.getLogger(__name__)

# The server no longer recognizes the connection id, usually after a restart. The mcp
# client synthesizes this error itself (mcp.client.streamable_http._send_session_terminated_error,
# mcp 1.30.0); it is not sent by the remote server, so the code is stable across MCP server
# implementations. Matched first; the message is a fallback for a client or transport that
# raises McpError for the same condition without this code.
_SESSION_TERMINATED_CODE = 32600
_SESSION_TERMINATED_MESSAGE = "session terminated"
# Raised by strands when the connection's background thread has exited. No error code is
# attached, so only the message is available to match on.
_CONNECTION_CLOSED_MESSAGE = "connection to the mcp server was closed"
_MAX_CAUSE_DEPTH = 5

# The connection number a call was sent on. call_tool_async sets it, and the SDK calls
# _handle_tool_execution_error inside that same call, so the handler can read it.
_call_connection_number: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_call_connection_number", default=None
)


def _is_connection_failure(exc: BaseException) -> bool:
    """Return True if exc, or an exception it was raised from, shows a dead MCP connection."""
    current: BaseException | None = exc
    for _ in range(_MAX_CAUSE_DEPTH):
        if current is None:
            return False
        if isinstance(current, McpError) and (
            current.error.code == _SESSION_TERMINATED_CODE
            or current.error.message.strip().lower() == _SESSION_TERMINATED_MESSAGE
        ):
            return True
        if isinstance(current, RuntimeError) and str(current).strip().lower() == _CONNECTION_CLOSED_MESSAGE:
            return True
        # Timeouts and UnsupportedProtocol are TransportErrors too, but the connection
        # is still the one every conversation shares. Only a broken network or protocol
        # means it is dead.
        if isinstance(current, (httpx.NetworkError, httpx.ProtocolError, MCPClientInitializationError)):
            return True
        current = current.__cause__ or current.__context__
    return False


class _ReconnectCircuit:
    """Stops reconnect attempts after repeated failures, then allows one per reset interval.

    Not thread-safe on its own. ReconnectingMCPClient only uses it under its reconnect lock.
    """

    def __init__(self, threshold: int, reset_interval: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._threshold = threshold
        self._reset_interval = reset_interval
        self._clock = clock
        self._failure_count = 0
        self._opened_at: float | None = None

    def allows_attempt(self) -> bool:
        """Return True when closed, or when open and the reset interval has passed."""
        if self._opened_at is None:
            return True
        return self._clock() - self._opened_at >= self._reset_interval

    def record_failure(self) -> bool:
        """Count a failed attempt. Return True if this opened the circuit, or reopened it."""
        self._failure_count += 1
        if self._failure_count >= self._threshold:
            self._opened_at = self._clock()
            return True
        return False

    def record_success(self) -> bool:
        """Reset the circuit. Return True if it was open."""
        was_open = self._opened_at is not None
        self._failure_count = 0
        self._opened_at = None
        return was_open


class ReconnectingMCPClient(MCPClient):
    """``MCPClient`` that reopens its MCP connection when the connection is broken.

    The client is stale when its connection is not running, or when a call failed
    with a dead-connection error. A stale client reconnects before the next tool
    call is sent. Concurrent calls share one reconnect. A circuit breaker stops
    reconnect attempts after ``circuit_threshold`` consecutive failures and allows
    one attempt every ``circuit_reset_interval`` seconds after that.

    A reconnect briefly clears ``_tool_provider_started`` and ``_consumers`` (``stop()``
    does that) before restoring them, so ``load_tools()`` - called directly by the SDK for
    a new agent, with no reconnect awareness of its own - waits on ``_reconnect_lock`` too.
    Otherwise it could run inside that window and see the restored flag before the
    connection is actually ready.

    ``add_consumer()`` and ``remove_consumer()`` must never block - the SDK calls them
    synchronously from ``Agent.__del__``, so waiting on ``_reconnect_lock`` there could
    freeze the event loop for the length of a reconnect. Each instead tries the lock
    without blocking: if it is free, the change applies immediately; if a reconnect is
    running, the change is queued in ``_pending_consumer_ops`` and ``_reconnect()`` applies
    it after its own restore of ``_consumers``, so it cannot be silently undone.
    """

    def __init__(
        self,
        transport_callable: Any,
        *,
        server_name: str,
        destination_host: str,
        circuit_threshold: int = 5,
        circuit_reset_interval: float = 60.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(transport_callable, **kwargs)
        self._reconnect_server_name = server_name
        self._reconnect_destination_host = destination_host
        self._reconnect_lock = threading.Lock()
        # add_consumer()/remove_consumer() must never block (the SDK calls them from Agent
        # finalizers), so one queues here instead of waiting out an in-flight reconnect.
        # Guarded by its own lock, separate from _reconnect_lock, since it is only ever
        # held briefly to append or drain - never while waiting on anything else.
        self._pending_lock = threading.Lock()
        self._pending_consumer_ops: list[tuple[str, Any, dict[str, Any]]] = []
        self._reconnect_stale = False
        # Goes up by one on each successful reconnect, so an error from an older
        # connection can be told apart from an error on the current one.
        self._connection_number = 1
        # Lets a call that waited on a failed reconnect share its error instead of
        # starting another attempt.
        self._reconnect_attempts_finished = 0
        self._last_reconnect_error: BaseException | None = None
        self._reconnect_circuit = _ReconnectCircuit(circuit_threshold, circuit_reset_interval)

    def _log_extra(self) -> dict[str, str]:
        return {"server_name": self._reconnect_server_name, "destination_host": self._reconnect_destination_host}

    def _connection_broken(self) -> bool:
        # Only a client some agent is using is reconnected. A client with no consumers
        # was stopped by the SDK on purpose, and the next agent starts it again.
        if not self._consumers:
            return False
        return self._reconnect_stale or not self._is_session_active()

    def _needs_reconnect(self) -> bool:
        # A call that arrives during a reconnect waits for it, rather than being sent
        # on a connection that is not ready yet.
        return self._reconnect_lock.locked() or self._connection_broken()

    def _reconnect(self) -> None:
        """Reopen the connection. Blocking: run it off the event loop."""
        attempts_before_wait = self._reconnect_attempts_finished
        try:
            with self._reconnect_lock:
                # Another caller may have reconnected while this one waited for the lock.
                if not self._connection_broken():
                    return
                # Or an attempt finished and failed while this one waited. Share that
                # failure rather than trying again at once.
                if self._reconnect_attempts_finished != attempts_before_wait and self._last_reconnect_error is not None:
                    raise MCPClientInitializationError("MCP reconnect failed") from self._last_reconnect_error
                if not self._reconnect_circuit.allows_attempt():
                    raise MCPClientInitializationError("MCP reconnect circuit is open; not reconnecting yet")

                # stop() clears both, so restore them to keep the SDK's reference counting intact.
                consumers = set(self._consumers)
                tool_provider_started = self._tool_provider_started
                logger.info("Reconnecting MCP client", extra=self._log_extra())
                try:
                    try:
                        self.stop(None, None, None)
                    except RuntimeError:
                        # The old connection's close error. It is already known to be dead.
                        pass
                    finally:
                        self._consumers = consumers | self._consumers
                        self._tool_provider_started = tool_provider_started
                    self.start()
                except Exception as exc:
                    # A failed start() calls stop() itself, which clears them again. Consumers
                    # are restored, but the started flag is not: start() never succeeded, so
                    # the next load_tools() must retry it instead of trusting a dead session.
                    self._consumers = consumers | self._consumers
                    self._tool_provider_started = False
                    self._last_reconnect_error = exc
                    self._reconnect_attempts_finished += 1
                    if self._reconnect_circuit.record_failure():
                        logger.warning("MCP reconnect circuit opened", extra=self._log_extra())
                    logger.warning(
                        "MCP reconnect failed",
                        extra={**self._log_extra(), "error_type": type(exc).__name__},
                    )
                    raise MCPClientInitializationError("MCP reconnect failed") from exc

                # start() succeeded, so the session is running. The captured flag can still
                # be False when an earlier attempt failed, and load_tools() would then call
                # start() again on this live session.
                self._tool_provider_started = True
                self._last_reconnect_error = None
                self._reconnect_attempts_finished += 1
                # Bump before clearing the stale flag. A late error from the connection being
                # replaced still carries the old number; clearing the flag first lets that
                # error match the current number and mark the new session stale.
                self._connection_number += 1
                self._reconnect_stale = False
                if self._reconnect_circuit.record_success():
                    logger.info("MCP reconnect circuit closed", extra=self._log_extra())
                logger.info("MCP client reconnected", extra=self._log_extra())
        finally:
            # Runs after the lock is released, so on every exit path the consumer changes
            # queued during this reconnect are applied after its _consumers restore.
            self._flush_pending_consumer_ops()

    def _apply_pending_consumer_ops(self) -> None:
        """Apply queued consumer changes in order. Caller must hold _reconnect_lock."""
        while True:
            with self._pending_lock:
                ops, self._pending_consumer_ops = self._pending_consumer_ops, []
            if not ops:
                return
            for op, consumer_id, kwargs in ops:
                try:
                    self._apply_consumer_op(op, consumer_id, kwargs)
                except Exception as exc:
                    # Logged, not raised: this may run inside _reconnect()'s finally, where
                    # raising would replace the reconnect's own error, and it may be applying
                    # another thread's change, whose caller has already returned.
                    logger.warning(
                        "Failed to apply queued MCP consumer change",
                        extra={**self._log_extra(), "error_type": type(exc).__name__},
                    )

    def _flush_pending_consumer_ops(self) -> None:
        """Apply queued consumer changes if _reconnect_lock is free. Never blocks.

        Every holder of _reconnect_lock calls this after releasing it, and every caller
        that queues a change calls it after queuing. So whichever thread is last to touch
        the lock drains the queue, and a queued change is never left behind.
        """
        while self._has_pending_consumer_ops() and self._reconnect_lock.acquire(blocking=False):
            try:
                self._apply_pending_consumer_ops()
            finally:
                self._reconnect_lock.release()

    def _has_pending_consumer_ops(self) -> bool:
        with self._pending_lock:
            return bool(self._pending_consumer_ops)

    def _apply_consumer_op(self, op: str, consumer_id: Any, kwargs: dict[str, Any]) -> None:
        if op == "add":
            super().add_consumer(consumer_id, **kwargs)
        else:
            super().remove_consumer(consumer_id, **kwargs)
            # The last agent left, so the SDK stopped this client. The stale flag belonged
            # to that connection; the next agent starts a new one.
            if not self._consumers:
                self._reconnect_stale = False

    def _change_consumer(self, op: str, consumer_id: Any, kwargs: dict[str, Any]) -> None:
        # Never blocks: the SDK calls add_consumer()/remove_consumer() from Agent
        # finalizers, which must not wait out an in-flight reconnect.
        if self._reconnect_lock.acquire(blocking=False):
            try:
                # Apply earlier queued changes first, so changes for one consumer stay in order.
                self._apply_pending_consumer_ops()
                self._apply_consumer_op(op, consumer_id, kwargs)
            finally:
                self._reconnect_lock.release()
        else:
            with self._pending_lock:
                self._pending_consumer_ops.append((op, consumer_id, kwargs))
        self._flush_pending_consumer_ops()

    def _wait_for_reconnect(self) -> None:
        # Acquire and release in the same worker-thread call, so cancelling the
        # asyncio.to_thread() await in load_tools() can never land between them and
        # leave the lock held with nothing left to release it.
        with self._reconnect_lock:
            pass
        self._flush_pending_consumer_ops()

    @override
    async def load_tools(self, **kwargs: Any) -> Sequence[AgentTool]:
        # Waits out an in-flight reconnect rather than running inside its restore
        # window, where _tool_provider_started can read True before start() has
        # actually reopened the connection.
        await asyncio.to_thread(self._wait_for_reconnect)
        return await super().load_tools(**kwargs)

    @override
    def add_consumer(self, consumer_id: Any, **kwargs: Any) -> None:
        self._change_consumer("add", consumer_id, kwargs)

    @override
    def remove_consumer(self, consumer_id: Any, **kwargs: Any) -> None:
        self._change_consumer("remove", consumer_id, kwargs)

    @override
    async def call_tool_async(self, *args: Any, **kwargs: Any) -> MCPToolResult:
        # The call has not been sent yet, so reconnecting first is safe.
        if self._needs_reconnect():
            await asyncio.to_thread(self._reconnect)
        token = _call_connection_number.set(self._connection_number)
        try:
            return await super().call_tool_async(*args, **kwargs)
        finally:
            _call_connection_number.reset(token)

    @override
    def _handle_tool_execution_error(self, tool_use_id: str, exception: Exception) -> MCPToolResult:
        # The call was already sent, so it is not retried. The next call reconnects.
        # An error from a connection that was already replaced says nothing about the
        # current one, so it must not trigger another reconnect.
        call_connection_number = _call_connection_number.get()
        on_current_connection = call_connection_number in (None, self._connection_number)
        if on_current_connection and _is_connection_failure(exception):
            self._reconnect_stale = True
            logger.warning(
                "MCP connection lost; reconnecting before the next call",
                extra={**self._log_extra(), "error_type": type(exception).__name__},
            )
        return super()._handle_tool_execution_error(tool_use_id, exception)
