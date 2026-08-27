from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, cast

from .common import runtime_subprocess_kwargs, terminate_runtime_process

ProcessStartedCallback = Callable[[int, datetime], Awaitable[None]]
ProcessExitedCallback = Callable[[int, int | None, datetime], Awaitable[None]]
ProcessChunkCallback = Callable[[bytes], Awaitable[None]]
ProcessFallbackCallback = Callable[[PermissionError], Awaitable[None]]


def _supports_windows_blocking_fallback() -> bool:
    """Return whether the Windows-only blocking spawn fallback is available."""

    return os.name == "nt"


@dataclass(frozen=True)
class LocalProcessResult:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    cancelled: bool = False
    signal: str | None = None


class LocalProcessSupervisor:
    """Own one local subprocess from spawn through output drain and exit."""

    async def run(
        self,
        command: str,
        *args: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        input_data: bytes | None = None,
        timeout_sec: float = 0,
        cancel_event: asyncio.Event | None = None,
        on_process_started: ProcessStartedCallback | None = None,
        on_process_exited: ProcessExitedCallback | None = None,
        on_stdout_chunk: ProcessChunkCallback | None = None,
        on_stderr_chunk: ProcessChunkCallback | None = None,
        stdin: int | None = None,
        allow_blocking_fallback: bool = False,
        on_blocking_fallback: ProcessFallbackCallback | None = None,
    ) -> LocalProcessResult:
        try:
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE if input_data is not None else stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **runtime_subprocess_kwargs(),
            )
        except PermissionError as exc:
            if not allow_blocking_fallback or not _supports_windows_blocking_fallback():
                raise
            if on_blocking_fallback is not None:
                await on_blocking_fallback(exc)
            return await self._run_blocking_fallback(
                command,
                *args,
                cwd=cwd,
                env=env,
                input_data=input_data,
                timeout_sec=timeout_sec,
                cancel_event=cancel_event,
                on_process_started=on_process_started,
                on_process_exited=on_process_exited,
                on_stdout_chunk=on_stdout_chunk,
                on_stderr_chunk=on_stderr_chunk,
                stdin=stdin,
            )
        pid = getattr(process, "pid", None)
        try:
            if on_process_started is not None and isinstance(pid, int):
                await on_process_started(pid, datetime.now(UTC))
            if self._supports_streaming(process) and (
                on_stdout_chunk is not None or on_stderr_chunk is not None
            ):
                result = await self._run_streaming(
                    process,
                    input_data=input_data,
                    timeout_sec=timeout_sec,
                    cancel_event=cancel_event,
                    on_stdout_chunk=on_stdout_chunk,
                    on_stderr_chunk=on_stderr_chunk,
                )
            else:
                result = await self._run_buffered(
                    process,
                    input_data=input_data,
                    timeout_sec=timeout_sec,
                    cancel_event=cancel_event,
                )
                if result.stdout and on_stdout_chunk is not None:
                    await on_stdout_chunk(result.stdout)
                if result.stderr and on_stderr_chunk is not None:
                    await on_stderr_chunk(result.stderr)
            return result
        except BaseException:
            if getattr(process, "returncode", None) is None:
                await terminate_runtime_process(process)
            raise
        finally:
            if on_process_exited is not None and isinstance(pid, int):
                await on_process_exited(
                    pid, getattr(process, "returncode", None), datetime.now(UTC)
                )

    async def _run_blocking_fallback(
        self,
        command: str,
        *args: str,
        cwd: str | None,
        env: dict[str, str] | None,
        input_data: bytes | None,
        timeout_sec: float,
        cancel_event: asyncio.Event | None,
        on_process_started: ProcessStartedCallback | None,
        on_process_exited: ProcessExitedCallback | None,
        on_stdout_chunk: ProcessChunkCallback | None,
        on_stderr_chunk: ProcessChunkCallback | None,
        stdin: int | None,
    ) -> LocalProcessResult:
        process = cast(
            "subprocess.Popen[bytes]",
            await asyncio.to_thread(
                subprocess.Popen,
                [command, *args],
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE if input_data is not None else stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **runtime_subprocess_kwargs(),
            ),
        )
        try:
            if on_process_started is not None:
                await on_process_started(process.pid, datetime.now(UTC))
            if (
                (on_stdout_chunk is not None or on_stderr_chunk is not None)
                and getattr(process, "stdout", None) is not None
                and getattr(process, "stderr", None) is not None
            ):
                return await self._run_blocking_streaming(
                    process,
                    input_data=input_data,
                    timeout_sec=timeout_sec,
                    cancel_event=cancel_event,
                    on_stdout_chunk=on_stdout_chunk,
                    on_stderr_chunk=on_stderr_chunk,
                )
            communication = asyncio.create_task(
                asyncio.to_thread(
                    process.communicate,
                    input_data,
                )
            )
            cancelled = self._cancel_waiter(cancel_event)
            try:
                outcome = await self._wait_for_completion(
                    communication,
                    cancelled=cancelled,
                    timeout_sec=timeout_sec,
                )
                if outcome in {"cancelled", "timed_out"}:
                    await terminate_runtime_process(process)
                stdout, stderr = await communication
            except asyncio.CancelledError:
                await terminate_runtime_process(process)
                with contextlib.suppress(asyncio.CancelledError):
                    await communication
                raise
            finally:
                await self._cancel_task(cancelled)
            if stdout and on_stdout_chunk is not None:
                await on_stdout_chunk(stdout)
            if stderr and on_stderr_chunk is not None:
                await on_stderr_chunk(stderr)
            return self._result(
                process,
                stdout,
                stderr,
                cancelled=outcome == "cancelled",
                timed_out=outcome == "timed_out",
                signal="SIGTERM" if outcome == "cancelled" else None,
            )
        except BaseException:
            if process.poll() is None:
                await terminate_runtime_process(process)
            raise
        finally:
            if on_process_exited is not None:
                await on_process_exited(
                    process.pid, process.returncode, datetime.now(UTC)
                )

    async def _run_blocking_streaming(
        self,
        process: subprocess.Popen[bytes],
        *,
        input_data: bytes | None,
        timeout_sec: float,
        cancel_event: asyncio.Event | None,
        on_stdout_chunk: ProcessChunkCallback | None,
        on_stderr_chunk: ProcessChunkCallback | None,
    ) -> LocalProcessResult:
        assert process.stdout is not None
        assert process.stderr is not None
        stdin_task = asyncio.create_task(
            asyncio.to_thread(self._write_blocking_stdin, process, input_data)
        )
        stdout_task = asyncio.create_task(
            self._read_blocking_pipe(process.stdout, on_stdout_chunk)
        )
        stderr_task = asyncio.create_task(
            self._read_blocking_pipe(process.stderr, on_stderr_chunk)
        )
        wait_task = asyncio.create_task(asyncio.to_thread(process.wait))
        cancelled = self._cancel_waiter(cancel_event)
        tasks = (stdin_task, stdout_task, stderr_task, wait_task)
        try:
            outcome = await self._wait_for_completion(
                wait_task,
                cancelled=cancelled,
                timeout_sec=timeout_sec,
            )
            if outcome in {"cancelled", "timed_out"}:
                await terminate_runtime_process(process)
            await stdin_task
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
            await wait_task
            return self._result(
                process,
                stdout,
                stderr,
                cancelled=outcome == "cancelled",
                timed_out=outcome == "timed_out",
                signal="SIGTERM" if outcome == "cancelled" else None,
            )
        except asyncio.CancelledError:
            await terminate_runtime_process(process)
            for task in tasks:
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks)
            raise
        finally:
            await self._cancel_task(cancelled)

    @staticmethod
    def _write_blocking_stdin(
        process: subprocess.Popen[bytes], input_data: bytes | None
    ) -> None:
        if process.stdin is None:
            return
        try:
            if input_data:
                process.stdin.write(input_data)
                process.stdin.flush()
        finally:
            process.stdin.close()

    @staticmethod
    async def _read_blocking_pipe(
        pipe: Any, callback: ProcessChunkCallback | None
    ) -> bytes:
        chunks: list[bytes] = []
        read = getattr(pipe, "read1", pipe.read)
        while True:
            chunk = await asyncio.to_thread(read, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
            if callback is not None:
                await callback(chunk)
        return b"".join(chunks)

    async def _run_buffered(
        self,
        process: asyncio.subprocess.Process,
        *,
        input_data: bytes | None,
        timeout_sec: float,
        cancel_event: asyncio.Event | None,
    ) -> LocalProcessResult:
        communication = asyncio.create_task(
            process.communicate(input_data)
            if input_data is not None
            else process.communicate()
        )
        cancelled = self._cancel_waiter(cancel_event)
        try:
            outcome = await self._wait_for_completion(
                communication,
                cancelled=cancelled,
                timeout_sec=timeout_sec,
            )
            if outcome == "cancelled":
                await terminate_runtime_process(process)
                stdout, stderr = await communication
                return self._result(
                    process,
                    stdout,
                    stderr,
                    cancelled=True,
                    signal="SIGTERM",
                )
            if outcome == "timed_out":
                await terminate_runtime_process(process)
                stdout, stderr = await communication
                return self._result(process, stdout, stderr, timed_out=True)
            stdout, stderr = communication.result()
            return self._result(process, stdout, stderr)
        except asyncio.CancelledError:
            await terminate_runtime_process(process)
            with contextlib.suppress(asyncio.CancelledError):
                await communication
            raise
        finally:
            await self._cancel_task(cancelled)

    async def _run_streaming(
        self,
        process: asyncio.subprocess.Process,
        *,
        input_data: bytes | None,
        timeout_sec: float,
        cancel_event: asyncio.Event | None,
        on_stdout_chunk: ProcessChunkCallback | None,
        on_stderr_chunk: ProcessChunkCallback | None,
    ) -> LocalProcessResult:
        stdin_task = asyncio.create_task(self._write_stdin(process, input_data))
        stdout_task = asyncio.create_task(
            self._read_pipe(process.stdout, on_stdout_chunk)
        )
        stderr_task = asyncio.create_task(
            self._read_pipe(process.stderr, on_stderr_chunk)
        )
        wait_task = asyncio.create_task(process.wait())
        cancelled = self._cancel_waiter(cancel_event)
        try:
            outcome = await self._wait_for_completion(
                wait_task,
                cancelled=cancelled,
                timeout_sec=timeout_sec,
            )
            if outcome in {"cancelled", "timed_out"}:
                await terminate_runtime_process(process)
            await stdin_task
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
            await wait_task
            return self._result(
                process,
                stdout,
                stderr,
                cancelled=outcome == "cancelled",
                timed_out=outcome == "timed_out",
                signal="SIGTERM" if outcome == "cancelled" else None,
            )
        except asyncio.CancelledError:
            await terminate_runtime_process(process)
            for task in (stdin_task, stdout_task, stderr_task, wait_task):
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(stdin_task, stdout_task, stderr_task, wait_task)
            raise
        finally:
            await self._cancel_task(cancelled)

    @staticmethod
    async def _wait_for_completion(
        completion: asyncio.Task,
        *,
        cancelled: asyncio.Task[bool] | None,
        timeout_sec: float,
    ) -> str:
        waiters = {completion}
        if cancelled is not None:
            waiters.add(cancelled)
        done, _ = await asyncio.wait(
            waiters,
            timeout=timeout_sec if timeout_sec > 0 else None,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled is not None and cancelled in done:
            return "cancelled"
        if completion not in done:
            return "timed_out"
        return "completed"

    @staticmethod
    def _cancel_waiter(cancel_event: asyncio.Event | None) -> asyncio.Task[bool] | None:
        if cancel_event is None:
            return None
        return asyncio.create_task(cancel_event.wait())

    @staticmethod
    async def _cancel_task(task: asyncio.Task | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @staticmethod
    async def _write_stdin(
        process: asyncio.subprocess.Process, input_data: bytes | None
    ) -> None:
        if process.stdin is None:
            return
        if input_data:
            process.stdin.write(input_data)
            await process.stdin.drain()
        process.stdin.close()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            await process.stdin.wait_closed()

    @staticmethod
    async def _read_pipe(
        pipe: asyncio.StreamReader | None,
        callback: ProcessChunkCallback | None,
    ) -> bytes:
        if pipe is None:
            return b""
        chunks: list[bytes] = []
        while True:
            chunk = await pipe.read(65_536)
            if not chunk:
                break
            chunks.append(chunk)
            if callback is not None:
                await callback(chunk)
        return b"".join(chunks)

    @staticmethod
    def _supports_streaming(process: object) -> bool:
        return (
            getattr(process, "stdin", None) is not None
            and getattr(process, "stdout", None) is not None
            and getattr(process, "stderr", None) is not None
            and callable(getattr(process, "wait", None))
        )

    @staticmethod
    def _result(
        process: asyncio.subprocess.Process | subprocess.Popen[bytes],
        stdout: bytes,
        stderr: bytes,
        *,
        timed_out: bool = False,
        cancelled: bool = False,
        signal: str | None = None,
    ) -> LocalProcessResult:
        return LocalProcessResult(
            exit_code=getattr(process, "returncode", None),
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            cancelled=cancelled,
            signal=signal,
        )


local_process_supervisor = LocalProcessSupervisor()
