from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from typing import Any

from ..common import RuntimeCapabilityMixin, skill_snapshot_from_root
from ..types import RuntimeExecutionContext, RuntimeExecutionResult


class CodexLocalRuntimeAdapter(RuntimeCapabilityMixin):
    type = "codex_local"
    supports_local_agent_jwt = True
    agent_configuration_doc = (
        "Configure cwd, model, promptTemplate, env, timeoutSec and Codex CLI options."
    )
    quota_provider = "openai"

    async def list_models(self) -> list[dict[str, str]]:
        return [
            {"id": "gpt-5-codex", "label": "GPT-5 Codex"},
            {"id": "gpt-5", "label": "GPT-5"},
        ]

    def _skill_snapshot(
        self, config: dict[str, Any], desired_skills: list[str]
    ) -> dict[str, Any]:
        return skill_snapshot_from_root(
            runtime_type=self.type,
            config=config,
            desired_skills=desired_skills,
            mode="persistent",
            location_label="CODEX_HOME/skills",
        )

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        command = _string(context.config.get("command")) or "codex"
        cwd = context.config.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError("Codex adapter cwd must be a string")
        prompt = _string(context.config.get("promptTemplate")) or ""
        args = _build_args(context.config)
        env = dict(os.environ)
        configured_env = context.config.get("env")
        if isinstance(configured_env, dict):
            env.update(
                {
                    key: value
                    for key, value in configured_env.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
            )
        timeout = context.config.get("timeoutSec", 0)
        timeout_sec = float(timeout) if isinstance(timeout, (float, int)) else 0.0
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        pid = getattr(process, "pid", None)
        if context.on_process_started is not None and isinstance(pid, int):
            await context.on_process_started(pid, datetime.now(UTC))
        communication = asyncio.create_task(process.communicate(prompt.encode()))
        try:
            cancelled = (
                asyncio.create_task(context.cancel_event.wait())
                if context.cancel_event is not None
                else None
            )
            if cancelled is not None:
                done, _ = await asyncio.wait(
                    {communication, cancelled},
                    timeout=timeout_sec if timeout_sec > 0 else None,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancelled in done:
                    process.kill()
                    stdout, stderr = await communication
                    await process.wait()
                    return RuntimeExecutionResult(
                        exit_code=process.returncode,
                        signal="SIGTERM",
                        error_message="Run cancelled",
                        result_json={
                            "stdout": stdout.decode(errors="replace"),
                            "stderr": stderr.decode(errors="replace"),
                        },
                    )
                cancelled.cancel()
                if communication not in done:
                    raise TimeoutError
                stdout, stderr = communication.result()
            elif timeout_sec > 0:
                stdout, stderr = await asyncio.wait_for(
                    communication, timeout=timeout_sec
                )
            else:
                stdout, stderr = await communication
        except TimeoutError:
            communication.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await communication
            process.kill()
            stdout, stderr = await process.communicate()
            await process.wait()
            return RuntimeExecutionResult(
                exit_code=process.returncode,
                timed_out=True,
                error_message=f"Timed out after {timeout_sec:g}s",
                result_json={
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                },
            )
        except asyncio.CancelledError:
            communication.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await communication
            process.kill()
            await process.communicate()
            await process.wait()
            raise

        stdout_text = stdout.decode(errors="replace")
        stderr_text = stderr.decode(errors="replace")
        if stdout_text:
            await context.on_log("stdout", stdout_text)
        if stderr_text:
            await context.on_log("stderr", stderr_text)
        parsed = _parse_jsonl(stdout_text)
        error = None
        if process.returncode != 0:
            error = parsed["errorMessage"] or _first_line(stderr_text)
            error = error or f"Codex exited with code {process.returncode}"
        return RuntimeExecutionResult(
            exit_code=process.returncode,
            error_message=error,
            usage_json=parsed["usage"],
            session_id_after=parsed["sessionId"],
            result_json={
                "stdout": stdout_text,
                "stderr": stderr_text,
                "summary": parsed["summary"],
            },
        )


def _build_args(config: dict[str, Any]) -> list[str]:
    args = ["exec", "--json", "--disable", "plugins"]
    if config.get("search") is True:
        args.insert(0, "--search")
    if config.get("dangerouslyBypassApprovalsAndSandbox") is True:
        args.append("--dangerously-bypass-approvals-and-sandbox")
    model = _string(config.get("model"))
    if model:
        args.extend(["--model", model])
    reasoning = _string(
        config.get("modelReasoningEffort") or config.get("reasoningEffort")
    )
    if reasoning:
        args.extend(["-c", f"model_reasoning_effort={json.dumps(reasoning)}"])
    extra_args = config.get("extraArgs", config.get("args", []))
    if isinstance(extra_args, list) and all(
        isinstance(argument, str) for argument in extra_args
    ):
        args.extend(extra_args)
    args.extend(["-c", "skills.bundled.enabled=false", "-"])
    return args


def _parse_jsonl(stdout: str) -> dict[str, Any]:
    session_id: str | None = None
    messages: list[str] = []
    error_message: str | None = None
    usage = {"inputTokens": 0, "cachedInputTokens": 0, "outputTokens": 0}
    for raw_line in stdout.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
            session_id = event["thread_id"]
        elif event_type == "error" and isinstance(event.get("message"), str):
            error_message = event["message"].strip() or error_message
        elif event_type == "item.completed":
            item = event.get("item")
            if (
                isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
            ):
                messages.append(item["text"])
        elif event_type == "turn.completed":
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                usage = {
                    "inputTokens": _integer(raw_usage.get("input_tokens")),
                    "cachedInputTokens": _integer(raw_usage.get("cached_input_tokens")),
                    "outputTokens": _integer(raw_usage.get("output_tokens")),
                }
        elif event_type == "turn.failed":
            raw_error = event.get("error")
            if isinstance(raw_error, dict) and isinstance(
                raw_error.get("message"), str
            ):
                error_message = raw_error["message"].strip() or error_message
    return {
        "sessionId": session_id,
        "summary": "\n\n".join(messages).strip(),
        "usage": usage,
        "errorMessage": error_message,
    }


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_line(value: str) -> str | None:
    return next((line.strip() for line in value.splitlines() if line.strip()), None)
