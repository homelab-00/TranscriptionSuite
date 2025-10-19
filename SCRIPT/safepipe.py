#!/usr/bin/env python3
"""
Provides a thread-safe wrapper for multiprocessing.Pipe.

This module addresses the challenge of using a multiprocessing pipe from multiple
threads within the parent process. It introduces the `SafePipe` function, which
returns a thread-safe parent connection that serializes all `send`, `recv`, and
`poll` operations through a dedicated worker thread, preventing race conditions
and ensuring stable inter-process communication.

Original Author: Kolja Beigel
Integrated by: homelab-00
"""

import logging
import multiprocessing as mp
import queue
import sys
import threading
from typing import Any, Optional, TypeGuard, cast

# Configure logging. Adjust level and formatting as needed.
# logging.basicConfig(level=logging.DEBUG,
#                     format='[%(asctime)s] %(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__)

try:
    if sys.platform.startswith("linux") or sys.platform == "darwin":
        mp.set_start_method("spawn")
    else:
        current_method: Optional[str] = cast(
            Optional[str], mp.get_start_method(allow_none=True)
        )
        if current_method is None:
            mp.set_start_method("spawn")
except RuntimeError as e:
    logger.debug("Start method has already been set. Details: %s", e)


def _is_two_tuple_with_bytes(value: Any) -> TypeGuard[tuple[Any, bytes]]:
    if not isinstance(value, tuple):
        return False
    value_tuple = cast(tuple[Any, ...], value)
    if len(value_tuple) != 2:
        return False
    return isinstance(value_tuple[1], bytes)


class ParentPipe:
    """
    A thread-safe wrapper around the 'parent end' of a multiprocessing pipe.
    All actual pipe operations happen in a dedicated worker thread, so it's safe
    for multiple threads to call send(), recv(), or poll() on the same ParentPipe
    without interfering.
    """

    def __init__(
        self, parent_synthesize_pipe: Any
    ) -> None:  # Connection type from mp.Pipe()
        self.name = "ParentPipe"
        self._pipe = parent_synthesize_pipe  # The raw pipe.
        self._closed = False  # A flag to mark if close() has been called.

        # The request queue for sending operations to the worker.
        self._request_queue: queue.Queue[dict[str, Any]] = queue.Queue()

        # This event signals the worker thread to stop.
        self._stop_event = threading.Event()

        # Worker thread that executes actual .send(), .recv(), .poll() calls.
        self._worker_thread = threading.Thread(
            target=self._pipe_worker, name=f"{self.name}_Worker", daemon=True
        )
        self._worker_thread.start()

    def _pipe_worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                request: dict[str, Any] = self._request_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if request["type"] == "CLOSE":
                # Exit worker loop on CLOSE request.
                break

            try:
                if request["type"] == "SEND":
                    data: Any = request["data"]
                    logger.debug("[%s] Worker: sending => %s", self.name, data)
                    self._pipe.send(data)
                    result_queue: queue.Queue[Any] = request["result_queue"]
                    result_queue.put(None)

                elif request["type"] == "RECV":
                    logger.debug("[%s] Worker: receiving...", self.name)
                    data = self._pipe.recv()
                    result_queue = request["result_queue"]
                    result_queue.put(data)

                elif request["type"] == "POLL":
                    timeout: float = request.get("timeout", 0.0)
                    logger.debug(
                        "[%s] Worker: poll() with timeout: %s", self.name, timeout
                    )
                    result: bool = self._pipe.poll(timeout)
                    result_queue = request["result_queue"]
                    result_queue.put(result)

            except (EOFError, BrokenPipeError, OSError) as e:
                # When the other end has closed or an error occurs,
                # log and notify the waiting thread.
                logger.debug(
                    "[%s] Worker: pipe closed or error occurred (%s). Shutting down.",
                    self.name,
                    e,
                )
                result_queue = request["result_queue"]
                result_queue.put(None)
                break

            except Exception as e:
                logger.exception("[%s] Worker: unexpected error.", self.name)
                result_queue = request["result_queue"]
                result_queue.put(e)
                break

        logger.debug("[%s] Worker: stopping.", self.name)
        try:
            self._pipe.close()
        except Exception as e:
            logger.debug("[%s] Worker: error during pipe close: %s", self.name, e)

    def send(self, data: Any) -> None:
        """
        Synchronously asks the worker thread to perform .send().
        """
        if self._closed:
            logger.debug("[%s] send() called but pipe is already closed", self.name)
            return
        logger.debug("[%s] send() requested with: %s", self.name, data)
        result_queue: queue.Queue[Any] = queue.Queue()
        request: dict[str, Any] = {
            "type": "SEND",
            "data": data,
            "result_queue": result_queue,
        }
        self._request_queue.put(request)
        result_queue.get()  # Wait until sending completes.
        logger.debug("[%s] send() completed", self.name)

    def recv(self) -> Any:
        """
        Synchronously asks the worker to perform .recv() and returns the data.
        """
        if self._closed:
            logger.debug("[%s] recv() called but pipe is already closed", self.name)
            return None
        logger.debug("[%s] recv() requested", self.name)
        result_queue: queue.Queue[Any] = queue.Queue()
        request: dict[str, Any] = {"type": "RECV", "result_queue": result_queue}
        self._request_queue.put(request)
        data: Any = result_queue.get()

        # Log a preview for huge byte blobs.
        data_preview: Any = data
        if _is_two_tuple_with_bytes(data):
            data_preview = (data[0], f"<{len(data[1])} bytes>")
        logger.debug("[%s] recv() returning => %s", self.name, data_preview)
        return data

    def poll(self, timeout: float = 0.0) -> bool:
        """
        Synchronously checks whether data is available.
        Returns True if data is ready, or False otherwise.
        """
        if self._closed:
            return False
        logger.debug("[%s] poll() requested with timeout: %s", self.name, timeout)
        result_queue: queue.Queue[Any] = queue.Queue()
        request: dict[str, Any] = {
            "type": "POLL",
            "timeout": timeout,
            "result_queue": result_queue,
        }
        self._request_queue.put(request)
        result: bool
        try:
            # Use a slightly longer timeout to give the worker a chance.
            result = result_queue.get(timeout=timeout + 0.1)
        except queue.Empty:
            result = False
        logger.debug("[%s] poll() returning => %s", self.name, result)
        return result

    def close(self) -> None:
        """
        Closes the pipe and stops the worker thread. The _closed flag makes
        sure no further operations are attempted.
        """
        if self._closed:
            return
        logger.debug("[%s] close() called", self.name)
        self._closed = True
        stop_request: dict[str, Any] = {"type": "CLOSE", "result_queue": queue.Queue()}
        self._request_queue.put(stop_request)
        self._stop_event.set()
        self._worker_thread.join()
        logger.debug("[%s] closed", self.name)


def SafePipe(debug: bool = False) -> tuple[ParentPipe, Any]:
    """
    Returns a pair: (thread-safe parent pipe, raw child pipe).
    """
    parent_synthesize_pipe, child_synthesize_pipe = mp.Pipe()
    parent_pipe = ParentPipe(parent_synthesize_pipe)
    return parent_pipe, child_synthesize_pipe
