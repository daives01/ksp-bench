from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.config import Scenario

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_NAME = "ksp"
REFERENCE_DIR = Path(".opencode/ksp/krpc_reference")

AGENT_PROMPT_TEMPLATE = """You are a KSP flight agent, your job is to fly the assigned Kerbal
Space Program vessel to the requested orbit.

Mission target:
- Body: {body}
- Target orbit: {target_altitude_m:.0f}m apoapsis and {target_altitude_m:.0f}m periapsis

Use the available KSP tools to accomplish this. Remember, KSP keeps flying in real wall-clock time
while you think and while tools run.

you have kRPC reference materials available at .opencode/ksp/krpc_reference.

Python snippets receive conn, space_center, vessel, observe(), getTelemetry(),
getVehicleState(), getOrbitState(), ksp_throttle(), ksp_stage(), ksp_attitude(),
sleep()/wait(), math, and time. Background tasks also receive should_stop().
"""

KRPC_REFERENCE_README = """# kRPC reference for the KSP flight agent

This directory contains kRPC source and Python client reference material for flight control.
Search it before guessing unfamiliar kRPC names or object paths.

for example there are:

- `installed_python_client/`: the installed `krpc` Python package, including generated service
  modules when the optional `krpc` dependency is installed.
- `upstream_python_client/`: `client/python/krpc` copied from the upstream kRPC repository.
- `upstream_spacecenter_service/`: `service/SpaceCenter/src/Services` copied from upstream kRPC.
- `upstream_docs/`: selected upstream API templates and tutorials.
"""


@dataclass(frozen=True)
class ExternalAgentResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    terminated: bool = False


class OpenCodeAgentAdapter:
    def __init__(
        self,
        *,
        model: str | None = None,
        thinking_level: str | None = None,
        executable: str | None = None,
        extra_args: list[str] | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.model = model
        # OpenCode calls a provider's reasoning setting a model "variant".
        # Keep benchmark runs comparable even when callers omit the flag.
        self.thinking_level = thinking_level or "low"
        self.executable = executable or "opencode"
        self.extra_args = extra_args or []
        self.project_root = project_root or PROJECT_ROOT

    @property
    def agent_metadata(self) -> dict[str, str | None]:
        return {
            "name": AGENT_NAME,
            "model": self.model,
            "thinking_level": self.thinking_level,
            "adapter": "opencode_cli_ksp_agent",
        }

    def run(
        self,
        *,
        scenario: Scenario,
        timeout_s: float | None,
        run_dir: Path | None = None,
        session_title: str | None = None,
        execution_timeout_s: float = 15.0,
        task_timeout_s: float = 180.0,
        max_sleep_s: float = 240.0,
        poll_interval_s: float = 0.5,
        stream_output: bool = True,
    ) -> ExternalAgentResult:
        prompt = build_agent_prompt(scenario=scenario)
        prepare_opencode_workspace(self.project_root)
        command = self._command(prompt, session_title=session_title)
        env = self._environment(
            scenario=scenario,
            run_dir=run_dir,
            execution_timeout_s=execution_timeout_s,
            task_timeout_s=task_timeout_s,
            max_sleep_s=max_sleep_s,
            poll_interval_s=poll_interval_s,
        )
        if stream_output:
            return _run_streaming(
                command,
                cwd=self.project_root,
                timeout_s=timeout_s,
                env=env,
                run_dir=run_dir,
            )
        return _run_captured(
            command,
            cwd=self.project_root,
            timeout_s=timeout_s,
            env=env,
            run_dir=run_dir,
        )

    def _command(self, prompt: str, *, session_title: str | None = None) -> list[str]:
        command = [
            self.executable,
            "run",
            "--dir",
            str(self.project_root),
            "--agent",
            AGENT_NAME,
            "--format",
            "json",
            "--auto",
        ]
        if self.model:
            command.extend(["--model", self.model])
        command.extend(["--variant", self.thinking_level])
        if session_title:
            command.extend(["--title", session_title])
        command.extend(self.extra_args)
        command.append(prompt)
        return command

    def _environment(
        self,
        *,
        scenario: Scenario,
        run_dir: Path | None,
        execution_timeout_s: float,
        task_timeout_s: float,
        max_sleep_s: float,
        poll_interval_s: float,
    ) -> dict[str, str]:
        env = dict(os.environ)
        if scenario.source_path is not None:
            env["KSPBENCH_SCENARIO"] = str(scenario.source_path.resolve())
        env["KSPBENCH_REFERENCE_ROOT"] = str((self.project_root / REFERENCE_DIR).resolve())
        env["KSPBENCH_EXECUTION_TIMEOUT"] = str(execution_timeout_s)
        env["KSPBENCH_TASK_TIMEOUT"] = str(task_timeout_s)
        env["KSPBENCH_MAX_SLEEP"] = str(max_sleep_s)
        env["KSPBENCH_POLL_INTERVAL"] = str(poll_interval_s)
        env["KSPBENCH_ENABLE_RESET_TOOL"] = "0"
        env.setdefault("KSPBENCH_PYTHON", sys.executable)
        if run_dir is not None:
            env["KSPBENCH_RUN_DIR"] = str(run_dir.resolve())
        return env


def prepare_opencode_workspace(
    project_root: Path = PROJECT_ROOT,
    *,
    krpc_repo: Path | None = None,
    include_installed: bool = True,
) -> dict[str, int]:
    reference_dir = project_root / REFERENCE_DIR
    reference_dir.mkdir(parents=True, exist_ok=True)
    (reference_dir / "README.md").write_text(KRPC_REFERENCE_README, encoding="utf-8")

    counts: dict[str, int] = {}
    _remove_generated_reference(reference_dir)

    if include_installed:
        installed_count = _copy_installed_krpc(reference_dir / "installed_python_client")
        if installed_count:
            counts["installed_python_client"] = installed_count

    source_repo = krpc_repo or _default_krpc_repo()
    if source_repo is not None:
        upstream_counts = _copy_upstream_krpc(source_repo, reference_dir)
        counts.update(upstream_counts)

    (reference_dir / "SOURCE_INDEX.md").write_text(_source_index(counts), encoding="utf-8")
    return counts


def _default_krpc_repo() -> Path | None:
    candidates = [
        os.environ.get("KSPBENCH_KRPC_REPO"),
        "/private/tmp/kspbench-krpc",
        "/tmp/kspbench-krpc",
    ]
    for value in candidates:
        if not value:
            continue
        path = Path(value)
        if (path / "client/python/krpc").is_dir():
            return path
    return None


def _remove_generated_reference(reference_dir: Path) -> None:
    for name in (
        "installed_python_client",
        "upstream_python_client",
        "upstream_spacecenter_service",
        "upstream_docs",
    ):
        path = reference_dir / name
        if path.exists():
            shutil.rmtree(path)


def _copy_installed_krpc(target: Path) -> int:
    try:
        import krpc  # type: ignore
    except Exception:
        return 0

    package_root = Path(krpc.__file__).resolve().parent
    return _copy_tree_filtered(
        package_root,
        target,
        suffixes={".py", ".pyi", ".typed"},
        exclude_parts={"__pycache__", "test", "tests"},
    )


def _copy_upstream_krpc(repo: Path, reference_dir: Path) -> dict[str, int]:
    copies = {
        "upstream_python_client": (
            repo / "client/python/krpc",
            reference_dir / "upstream_python_client/krpc",
            {".py", ".pyi", ".typed", ".txt", ".md"},
        ),
        "upstream_spacecenter_service": (
            repo / "service/SpaceCenter/src/Services",
            reference_dir / "upstream_spacecenter_service",
            {".cs"},
        ),
        "upstream_docs": (
            repo / "doc",
            reference_dir / "upstream_docs",
            {".rst", ".tmpl", ".py"},
        ),
    }
    counts: dict[str, int] = {}
    for name, (source, target, suffixes) in copies.items():
        if source.is_dir():
            count = _copy_tree_filtered(
                source,
                target,
                suffixes=suffixes,
                exclude_parts={"__pycache__", "test", "tests", "images", "_static"},
            )
            if count:
                counts[name] = count
    return counts


def _copy_tree_filtered(
    source_root: Path,
    target_root: Path,
    *,
    suffixes: set[str],
    exclude_parts: set[str],
) -> int:
    copied = 0
    for source in sorted(source_root.rglob("*")):
        relative = source.relative_to(source_root)
        if source.is_dir() or source.suffix not in suffixes:
            continue
        if exclude_parts.intersection(relative.parts):
            continue
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied += 1
    return copied


def _source_index(counts: dict[str, int]) -> str:
    lines = [
        "# kRPC source index",
        "",
        "Reference material available to the KSP flight agent.",
        "",
    ]
    if not counts:
        lines.extend(
            [
                "No kRPC source folders were available.",
                "",
                "Use the available KSP tools directly until reference material is available.",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.append("Available folders:")
    for name, count in sorted(counts.items()):
        lines.append(f"- `{name}/`: {count} files")
    lines.extend(
        [
            "",
            "High-value files when present:",
            "- `installed_python_client/services/spacecenter.py`",
            "- `upstream_spacecenter_service/Vessel.cs`",
            "- `upstream_spacecenter_service/AutoPilot.cs`",
            "- `upstream_spacecenter_service/Control.cs`",
            "- `upstream_spacecenter_service/Orbit.cs`",
            "- `upstream_docs/api/space-center/*.tmpl`",
        ]
    )
    return "\n".join(lines) + "\n"


def build_agent_prompt(*, scenario: Scenario) -> str:
    return AGENT_PROMPT_TEMPLATE.format(
        body=scenario.body,
        target_altitude_m=scenario.target_orbit.altitude_m,
        stable_periapsis_min_m=scenario.target_orbit.stable_periapsis_min_m,
        timeout_s=scenario.timeout_s,
    )


def _run_streaming(
    command: list[str],
    *,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    run_dir: Path | None = None,
) -> ExternalAgentResult:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return ExternalAgentResult(command=command, returncode=127, stdout="", stderr=str(exc))

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    threads = [
        threading.Thread(
            target=_tee_stream,
            args=(process.stdout, sys.stdout, stdout_chunks, _format_opencode_json_line),
            daemon=True,
        ),
        threading.Thread(
            target=_tee_stream,
            args=(process.stderr, sys.stderr, stderr_chunks, None),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    returncode, timed_out, terminated = _wait_for_process(
        process,
        timeout_s=timeout_s,
        run_dir=run_dir,
    )
    for thread in threads:
        thread.join(timeout=2.0)
    return ExternalAgentResult(
        command=command,
        returncode=returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        timed_out=timed_out,
        terminated=terminated,
    )


def _run_captured(
    command: list[str],
    *,
    cwd: Path,
    timeout_s: float | None,
    env: dict[str, str],
    run_dir: Path | None = None,
) -> ExternalAgentResult:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return ExternalAgentResult(command=command, returncode=127, stdout="", stderr=str(exc))

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    threads = [
        threading.Thread(
            target=_collect_stream,
            args=(process.stdout, stdout_chunks),
            daemon=True,
        ),
        threading.Thread(
            target=_collect_stream,
            args=(process.stderr, stderr_chunks),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    returncode, timed_out, terminated = _wait_for_process(
        process,
        timeout_s=timeout_s,
        run_dir=run_dir,
    )
    for thread in threads:
        thread.join(timeout=2.0)
    return ExternalAgentResult(
        command=command,
        returncode=returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        timed_out=timed_out,
        terminated=terminated,
    )


def _wait_for_process(
    process: subprocess.Popen[str],
    *,
    timeout_s: float | None,
    run_dir: Path | None,
) -> tuple[int, bool, bool]:
    deadline = threading.Event()
    timeout_timer = None
    if timeout_s is not None:
        timeout_timer = threading.Timer(timeout_s, deadline.set)
        timeout_timer.start()
    try:
        while process.poll() is None:
            if run_dir is not None and _run_was_terminated(run_dir):
                _stop_process(process)
                return process.wait(timeout=2.0), False, True
            if deadline.is_set():
                process.kill()
                return process.wait(timeout=2.0), True, False
            threading.Event().wait(0.1)
        return process.returncode or 0, False, False
    finally:
        if timeout_timer is not None:
            timeout_timer.cancel()


def _stop_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()


def _run_was_terminated(run_dir: Path) -> bool:
    events = run_dir / "events.jsonl"
    if not events.exists():
        return False
    try:
        lines = events.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(
        '"type": "run_terminated"' in line or '"type":"run_terminated"' in line
        for line in lines
    )


def _tee_stream(stream: Any, target: Any, chunks: list[str], formatter: Any = None) -> None:
    if stream is None:
        return
    for chunk in iter(stream.readline, ""):
        chunks.append(chunk)
        target.write(formatter(chunk) if formatter else chunk)
        target.flush()


def _collect_stream(stream: Any, chunks: list[str]) -> None:
    if stream is None:
        return
    for chunk in iter(stream.readline, ""):
        chunks.append(chunk)


def _format_opencode_json_line(line: str) -> str:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(event, dict):
        return line

    tool = _event_tool_name(event)
    if tool:
        return f"[agent] {tool}\n"
    text = _event_text(event)
    if text:
        return text if text.endswith("\n") else f"{text}\n"
    return ""


def _event_tool_name(event: dict[str, Any]) -> str | None:
    for key in ("tool", "toolName", "name"):
        value = event.get(key)
        if isinstance(value, str) and (value.startswith("ksp_") or value == "bash"):
            return value
    for value in event.values():
        if isinstance(value, dict):
            found = _event_tool_name(value)
            if found:
                return found
    return None


def _event_text(event: dict[str, Any]) -> str | None:
    for key in ("text", "content", "message"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return None


def _format_opencode_terminal_chunk(chunk: str) -> str:
    return "".join(_format_opencode_terminal_line(line) for line in chunk.splitlines(keepends=True))


def _format_opencode_terminal_line(line: str) -> str:
    line_body, line_end = _split_line_ending(line)
    clean = _strip_ansi(line_body).strip()
    clean = clean.removeprefix("> ").strip()
    if not clean:
        return ""
    match = re.fullmatch(
        r".*?(ksp_(?:observe|throttle|stage|attitude|wait|"
        r"execute_python|"
        r"start_task|check_task|stop_task))(?:\s+(.*))?",
        clean,
    )
    if not match:
        return line

    tool = match.group(1)
    payload = (match.group(2) or "").strip()
    if tool in {"ksp_observe", "ksp_stage", "ksp_check_task"}:
        return f"[agent] {tool}{(' ' + payload) if payload else ''}{line_end}"

    if not payload:
        return f"[agent] {tool}{line_end}"

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return f"[agent] {tool} {payload}{line_end}"

    if not isinstance(decoded, dict):
        return f"[agent] {tool} {json.dumps(decoded, sort_keys=True)}{line_end}"

    lines = [f"[agent] {tool}"]
    code = decoded.get("code")
    if isinstance(code, str):
        lines.append("  code:")
        lines.extend(f"    {code_line}" for code_line in code.rstrip().splitlines())
    timeout = decoded.get("timeout_s")
    if timeout is not None:
        lines.append(f"  timeout_s: {timeout}")
    extras = {key: value for key, value in decoded.items() if key not in {"code", "timeout_s"}}
    for key, value in sorted(extras.items()):
        lines.append(f"  {key}: {json.dumps(value, sort_keys=True)}")
    return "\n".join(lines) + line_end


def _split_line_ending(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body) :]


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def extract_usage(stdout: str, stderr: str) -> dict[str, int | float | None]:
    text = f"{stdout}\n{stderr}"
    usage_from_json = _extract_json_usage(text)
    if usage_from_json:
        return usage_from_json
    return {
        "input_tokens": _extract_int(text, r"(?:input|prompt)\s+tokens?[:=\s]+([\d,]+)"),
        "output_tokens": _extract_int(text, r"(?:output|completion)\s+tokens?[:=\s]+([\d,]+)"),
        "total_tokens": _extract_int(text, r"total\s+tokens?[:=\s]+([\d,]+)"),
        "cost_usd": _extract_float(text, r"(?:cost|total\s+cost)[:=\s]+\$?([0-9]+(?:\.[0-9]+)?)"),
    }


def _extract_json_usage(text: str) -> dict[str, int | float | None] | None:
    result: dict[str, int | float | None] = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost_usd": None,
    }
    found = False
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        usage = _find_usage_mapping(event)
        if not usage:
            continue
        found = True
        result["input_tokens"] = _coalesce_int(
            usage.get("input"),
            usage.get("inputTokens"),
            usage.get("prompt_tokens"),
            usage.get("promptTokens"),
            result["input_tokens"],
        )
        result["output_tokens"] = _coalesce_int(
            usage.get("output"),
            usage.get("outputTokens"),
            usage.get("completion_tokens"),
            usage.get("completionTokens"),
            result["output_tokens"],
        )
        result["total_tokens"] = _coalesce_int(
            usage.get("total"),
            usage.get("totalTokens"),
            result["total_tokens"],
        )
        result["cost_usd"] = _coalesce_float(
            usage.get("cost"),
            usage.get("costUsd"),
            usage.get("cost_usd"),
            result["cost_usd"],
        )
    if result["total_tokens"] is None and (
        result["input_tokens"] is not None or result["output_tokens"] is not None
    ):
        result["total_tokens"] = int(result["input_tokens"] or 0) + int(
            result["output_tokens"] or 0
        )
    return result if found else None


def _find_usage_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    usage = value.get("usage")
    if isinstance(usage, dict):
        return usage
    for nested in value.values():
        found = _find_usage_mapping(nested)
        if found:
            return found
    return None


def _coalesce_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int | float):
            return int(value)
    return None


def _coalesce_float(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, int | float):
            return float(value)
    return None


def _extract_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _extract_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))
