#!/usr/bin/env python3
"""Fixer: a Team of models your coding agent can consult, served over MCP.

The host agent (Claude Code, Codex, fx, ...) is the primary. Fixer gives it
one tool per Team member. A call runs that member through its own CLI, on
its own model, in the same workspace, and returns the member's answer.

- A specialist starts fresh on every call.
- A peer keeps one session with the primary for as long as this server runs.

Members do not consult each other.

Standard library only. Python 3.11+, macOS or Linux.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.3.0"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_TEAM_PATHS = (".fixer/team.toml", "fixer.toml")
MEMBER_ID = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
PRIMARY = "primary"
KINDS = ("peer", "specialist")
# Linux refuses a single argument longer than 128 KiB. Longer prompts go
# to a file that the member reads first.
MAX_ARG_PROMPT = 96 * 1024


class TeamError(ValueError):
    pass


class MemberError(RuntimeError):
    """A member ran but Fixer could not use its result."""


# -- Team file -------------------------------------------------------------


@dataclass(frozen=True)
class Member:
    id: str
    kind: str
    runner: str
    model: str
    description: str
    instructions: str = ""
    read_only: bool = True
    timeout_seconds: int | None = None


@dataclass
class Team:
    path: Path
    name: str
    members: dict[str, Member]
    commands: dict[str, tuple[str, ...]] = field(default_factory=dict)
    max_active: int = 6
    timeout_seconds: int = 900
    env: dict[str, str] = field(default_factory=dict)

    def adapter(self, member: Member) -> "Adapter":
        if member.runner in self.commands:
            return CommandAdapter(self.commands[member.runner])
        return ADAPTERS[member.runner]


def _strings(value, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise TeamError(f"{where} must be a list of non-empty strings")
    return tuple(value)


def _text(table: dict, key: str, where: str, required: bool = True) -> str:
    if key not in table:
        if required:
            raise TeamError(f"{where}: missing '{key}'")
        return ""
    value = table[key]
    if not isinstance(value, str) or (required and not value.strip()):
        raise TeamError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


def _reject_unknown(table: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise TeamError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _positive_int(table: dict, key: str, default: int | None, where: str) -> int | None:
    value = table.get(key, default)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise TeamError(f"{where}: '{key}' must be a positive integer")
    return value


def load_team(path: Path) -> Team:
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise TeamError(f"no Team file at {path}") from None
    except tomllib.TOMLDecodeError as err:
        raise TeamError(f"{path}: {err}") from None

    _reject_unknown(raw, {"name", "max_active", "timeout_seconds", "env", "commands", "members"},
                    str(path))

    commands: dict[str, tuple[str, ...]] = {}
    for name, argv in raw.get("commands", {}).items():
        if name in ADAPTERS:
            raise TeamError(f"commands.{name}: '{name}' is a built-in runner")
        commands[name] = _strings(argv, f"commands.{name}")

    members_raw = raw.get("members", {})
    if not isinstance(members_raw, dict) or not members_raw:
        raise TeamError(f"{path}: define at least one [members.<id>] table")

    members: dict[str, Member] = {}
    for member_id, spec in members_raw.items():
        where = f"members.{member_id}"
        if not MEMBER_ID.match(member_id):
            raise TeamError(f"{where}: ids are lowercase letters, digits, '-' and '_'")
        if member_id == PRIMARY:
            raise TeamError(f"{where}: '{PRIMARY}' is the host agent")
        if not isinstance(spec, dict):
            raise TeamError(f"{where} must be a table")
        _reject_unknown(spec, {"kind", "runner", "model", "description", "instructions",
                               "read_only", "timeout_seconds"}, where)
        kind = _text(spec, "kind", where)
        if kind not in KINDS:
            raise TeamError(f"{where}: 'kind' must be 'peer' or 'specialist'")
        runner = _text(spec, "runner", where)
        if runner not in ADAPTERS and runner not in commands:
            known = ", ".join(sorted(ADAPTERS) + sorted(commands))
            raise TeamError(f"{where}: unknown runner '{runner}' (known: {known})")
        read_only = spec.get("read_only", True)
        if not isinstance(read_only, bool):
            raise TeamError(f"{where}: 'read_only' must be true or false")
        member = Member(
            id=member_id, kind=kind, runner=runner,
            model=_text(spec, "model", where),
            description=_text(spec, "description", where),
            instructions=_text(spec, "instructions", where, required=False),
            read_only=read_only,
            timeout_seconds=_positive_int(spec, "timeout_seconds", None, where),
        )
        adapter = CommandAdapter(commands[runner]) if runner in commands else ADAPTERS[runner]
        if kind == "peer" and not adapter.sessions:
            raise TeamError(f"{where}: runner '{runner}' cannot resume a session headless, "
                            "so it can run specialists only")
        if not read_only and not adapter.can_write:
            raise TeamError(f"{where}: runner '{runner}' has no write mode")
        members[member_id] = member

    env = raw.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        raise TeamError("env must be a table of strings")

    return Team(
        path=path.resolve(),
        name=raw.get("name", path.resolve().parent.name or "team"),
        members=members,
        commands=commands,
        max_active=_positive_int(raw, "max_active", 6, str(path)),
        timeout_seconds=_positive_int(raw, "timeout_seconds", 900, str(path)),
        env=env,
    )


def find_team(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("FIXER_TEAM"):
        return Path(os.environ["FIXER_TEAM"]).expanduser()
    for candidate in DEFAULT_TEAM_PATHS:
        if Path(candidate).is_file():
            return Path(candidate)
    return Path(DEFAULT_TEAM_PATHS[0])


# -- Adapters: one per CLI -------------------------------------------------
#
# An adapter turns one consultation into a command line and reads the
# member's answer (and, for sessions, its session id) from the output.
# Everything that depends on a CLI's flags or output format lives here.


@dataclass
class Call:
    """One run of a member's CLI."""
    member: Member
    prompt: str
    session: str | None       # session to resume, or a new id the adapter chose
    resume: bool              # True: continue `session`; False: start fresh
    keep: bool                # True: the CLI must save the session for later calls
    timeout: int


@dataclass
class Invocation:
    argv: list[str]
    stdin: str | None = None
    env: dict[str, str] = field(default_factory=dict)


class Adapter:
    name = ""
    sessions = False          # can resume a session with no terminal
    can_write = True
    chooses_session_id = False  # Fixer picks the id (True) or reads it from output (False)

    def invoke(self, call: Call) -> Invocation:
        raise NotImplementedError

    def parse(self, stdout: str, call: Call) -> tuple[str, str | None]:
        """Return (answer, session id)."""
        raise NotImplementedError

    def new_session(self, member: Member, env: dict) -> str | None:
        """Create a session before the first call, for CLIs that need it."""
        return str(uuid.uuid4()) if self.chooses_session_id else None


def _json_lines(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def _json_object(stdout: str) -> dict:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        events = _json_lines(stdout)
        value = events[-1] if events else None
    if not isinstance(value, dict):
        raise MemberError("the CLI did not print a JSON result")
    return value


class ClaudeAdapter(Adapter):
    """Claude Code: claude -p. Fixer chooses the session id."""
    name = "claude"
    sessions = True
    chooses_session_id = True

    def invoke(self, call):
        argv = ["claude", "-p", "--output-format", "json", "--model", call.member.model]
        if call.resume:
            argv += ["--resume", call.session]
        elif call.keep:
            argv += ["--session-id", call.session]
        else:
            argv += ["--no-session-persistence"]
        # In -p mode Claude Code refuses actions it would ask about. Reads
        # need no approval; acceptEdits allows file edits as well.
        if not call.member.read_only:
            argv += ["--permission-mode", "acceptEdits"]
        return Invocation(argv, stdin=call.prompt)

    def parse(self, stdout, call):
        result = _json_object(stdout)
        if result.get("is_error"):
            raise MemberError(str(result.get("result") or result.get("subtype") or "error"))
        return str(result.get("result") or ""), result.get("session_id")


class CodexAdapter(Adapter):
    """OpenAI Codex: codex exec. Fixer reads the thread id from --json events."""
    name = "codex"
    sessions = True

    def invoke(self, call):
        sandbox = "read-only" if call.member.read_only else "workspace-write"
        options = ["--json", "--skip-git-repo-check", "-m", call.member.model,
                   "-c", f'sandbox_mode="{sandbox}"']
        if not call.keep:
            options += ["--ephemeral"]
        if call.resume:
            argv = ["codex", "exec", "resume", *options, call.session, "-"]
        else:
            argv = ["codex", "exec", *options, "-"]
        return Invocation(argv, stdin=call.prompt)

    def parse(self, stdout, call):
        thread, answer = None, None
        for event in _json_lines(stdout):
            kind = event.get("type")
            if kind == "thread.started":
                thread = event.get("thread_id")
            elif kind == "item.completed" and (event.get("item") or {}).get("type") == "agent_message":
                answer = event["item"].get("text")
            elif kind in ("turn.failed", "error"):
                detail = (event.get("error") or {}).get("message") or event.get("message")
                raise MemberError(str(detail or event))
        return answer or "", thread or call.session


class OpenCodeAdapter(Adapter):
    """OpenCode: opencode run. Read-only members use the built-in plan agent.

    The plan agent denies edits but allows shell commands. A config that also
    denies bash makes OpenCode's free tier refuse the request, so Fixer does
    not send one.
    """
    name = "opencode"
    sessions = True

    def invoke(self, call):
        argv = ["opencode", "run", "--format", "json", "-m", call.member.model]
        if call.resume:
            argv += ["--session", call.session]
        if call.member.read_only:
            argv += ["--agent", "plan"]
        return Invocation(argv + [call.prompt])

    def parse(self, stdout, call):
        session, texts = None, []
        for event in _json_lines(stdout):
            session = event.get("sessionID") or session
            kind = event.get("type")
            if kind == "step_start":
                texts = []  # keep only the last step's text: the final answer
            elif kind == "text":
                texts.append((event.get("part") or {}).get("text", ""))
            elif kind == "error":
                error = event.get("error") or {}
                raise MemberError(str((error.get("data") or {}).get("message") or error))
        return "".join(texts), session


class CursorAdapter(Adapter):
    """Cursor CLI: cursor-agent -p. A session is a chat made by create-chat.

    Written from cursor-agent's help text; not yet run with a real model.
    """
    name = "cursor"
    sessions = True

    def invoke(self, call):
        argv = ["cursor-agent", "-p", "--output-format", "json", "--trust",
                "--model", call.member.model]
        if call.session:
            argv += ["--resume", call.session]
        if call.member.read_only:
            argv += ["--mode", "ask"]
        else:
            argv += ["--force"]
        return Invocation(argv + [call.prompt])

    def new_session(self, member, env):
        done = subprocess.run(["cursor-agent", "create-chat"], capture_output=True, text=True,
                              env=env, timeout=60, stdin=subprocess.DEVNULL)
        chat = done.stdout.strip().splitlines()[-1:] if done.returncode == 0 else []
        if not chat:
            raise MemberError(f"cursor-agent create-chat failed: {done.stderr.strip()[-500:]}")
        return chat[0].strip()

    def parse(self, stdout, call):
        result = _json_object(stdout)
        if result.get("is_error"):
            raise MemberError(str(result.get("result") or "error"))
        return str(result.get("result") or ""), result.get("session_id") or call.session


class ClineAdapter(Adapter):
    """Cline CLI. It cannot resume a session headless, so specialists only.

    Plan mode blocks Cline's edit tools but still runs shell commands. With
    auto-approve off, every tool, reads included, needs approval that a
    headless run cannot give.
    """
    name = "cline"

    def invoke(self, call):
        argv = ["cline", "--json", "-m", call.member.model]
        # Cline approves every tool by default. Plan mode makes no edits.
        argv += ["--plan"] if call.member.read_only else ["--auto-approve", "true"]
        return Invocation(argv + [call.prompt])

    def parse(self, stdout, call):
        for event in reversed(_json_lines(stdout)):
            if event.get("type") == "run_result":
                if event.get("finishReason") != "completed":
                    raise MemberError(str(event.get("text") or event.get("finishReason")))
                return str(event.get("text") or ""), None
            if event.get("type") == "error":
                raise MemberError(str(event.get("message")))
        raise MemberError("cline printed no result")


class FxAdapter(Adapter):
    """fx: fx ask. Fixer reads the session id from --json output."""
    name = "fx"
    sessions = True

    def invoke(self, call):
        argv = ["fx", "ask", "--json", "--model", call.member.model]
        if call.resume:
            argv += ["--resume-id", call.session]
        elif not call.keep:
            argv += ["--no-save"]
        if not call.member.read_only:
            argv += ["--auto"]
        return Invocation(argv, stdin=call.prompt)

    def parse(self, stdout, call):
        result = _json_object(stdout)
        if result.get("exit_code", 0) != 0:
            raise MemberError(str(result.get("final_output") or result.get("error") or result))
        return str(result.get("final_output") or result.get("output") or ""), result.get("session_id")


class CommandAdapter(Adapter):
    """A custom command from [commands]: one-time calls, answer on stdout."""
    name = "command"
    can_write = False

    def __init__(self, template: tuple[str, ...]):
        self.template = template

    def invoke(self, call):
        argv = [part.replace("{model}", call.member.model) for part in self.template]
        if any("{prompt}" in part for part in argv):
            return Invocation([part.replace("{prompt}", call.prompt) for part in argv])
        return Invocation(argv, stdin=call.prompt)

    def parse(self, stdout, call):
        return stdout.strip(), None


ADAPTERS: dict[str, Adapter] = {a.name: a for a in (
    ClaudeAdapter(), CodexAdapter(), OpenCodeAdapter(), CursorAdapter(), ClineAdapter(), FxAdapter())}


# -- Prompts ---------------------------------------------------------------


def first_prompt(team: Team, member: Member, task: str, context: str) -> str:
    parts = [f'You are "{member.id}", a {member.kind} on the "{team.name}" team. '
             "The primary agent is consulting you."]
    if member.kind == "peer":
        parts.append("This is the start of your conversation with the primary. Its later "
                     "requests continue this conversation, so you keep what you learn here.")
    if member.instructions:
        parts.append(f"Your role:\n{member.instructions}")
    parts.append(_request(task, context))
    rules = "Work only on this request. Your final message goes back to the primary verbatim."
    if member.read_only:
        rules += " Do not modify files; report what should change instead."
    parts.append(rules)
    return "\n\n".join(parts)


def next_prompt(task: str, context: str) -> str:
    return "A new request from the primary.\n\n" + _request(task, context)


def _request(task: str, context: str) -> str:
    text = f"Task:\n{task.strip()}"
    if context.strip():
        text += f"\n\nContext from the primary:\n{context.strip()}"
    return text


# -- Limits ------------------------------------------------------------------


class ActiveSlots:
    """Counts live member runs for one Team, across processes.

    It limits parallel runs. It is also the backstop if a member's CLI loads
    Fixer from the user's own settings and its host drops FIXER_MEMBER.
    """

    def __init__(self, team: Team):
        key = hashlib.sha256(str(team.path).encode()).hexdigest()[:16]
        base = Path(os.environ.get("FIXER_RUN_DIR") or Path(tempfile.gettempdir()) / f"fixer-{os.getuid()}")
        self.dir = base / key
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.limit = team.max_active

    def acquire(self, label: str) -> Path | None:
        with open(self.dir / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            live = 0
            for slot in self.dir.glob("*.slot"):
                try:
                    os.kill(int(slot.read_text().split()[0]), 0)
                    live += 1
                except (ValueError, ProcessLookupError, IndexError):
                    slot.unlink(missing_ok=True)
                except PermissionError:
                    live += 1
            if live >= self.limit:
                return None
            slot = self.dir / f"{os.getpid()}-{threading.get_ident()}-{time.monotonic_ns()}.slot"
            slot.write_text(f"{os.getpid()} {label}\n")
            return slot

    @staticmethod
    def release(slot: Path) -> None:
        slot.unlink(missing_ok=True)


def log_event(**fields) -> None:
    """Append one JSON line to $FIXER_LOG, if set."""
    path = os.environ.get("FIXER_LOG")
    if path:
        with open(path, "a") as handle:
            handle.write(json.dumps({"time": round(time.time(), 3), "pid": os.getpid(), **fields}) + "\n")


def _kill(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# -- MCP server ------------------------------------------------------------


class Server:
    def __init__(self, team: Team, out=sys.stdout):
        self.team = team
        # A member's CLI can load Fixer from the user's own MCP settings. A
        # Fixer that runs inside a member offers no tools: members do not
        # consult each other.
        self.inside_member = bool(os.environ.get("FIXER_MEMBER"))
        self.out = out
        self.write_lock = threading.Lock()
        self.calls: dict[object, subprocess.Popen | None] = {}
        self.cancelled: set[object] = set()
        self.calls_lock = threading.Lock()
        self.slots = ActiveSlots(team)
        # The primary's session with each peer, and one lock per peer so that
        # two calls never resume the same session at the same time.
        self.sessions: dict[str, str] = {}
        self.peer_locks = {m: threading.Lock() for m in team.members}

    # transport

    def send(self, message: dict) -> None:
        line = json.dumps(message, separators=(",", ":"))
        with self.write_lock:
            self.out.write(line + "\n")
            self.out.flush()

    def reply(self, request_id, result=None, error=None) -> None:
        message = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            message["error"] = error
        else:
            message["result"] = result
        self.send(message)

    def serve(self, stream=sys.stdin) -> None:
        threads = []
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self.reply(None, error={"code": -32700, "message": "parse error"})
                continue
            if not isinstance(message, dict):
                self.reply(None, error={"code": -32600, "message": "invalid request"})
                continue
            thread = self.handle(message)
            if thread:
                threads.append(thread)
        # The host closed stdin: it is gone, so its consultations are too.
        self.cancel_all()
        for thread in threads:
            thread.join(timeout=5)

    def handle(self, message: dict) -> threading.Thread | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params")
        params = {} if params is None else params
        if method is None:
            return None  # a response to a request we never send
        if not isinstance(method, str) or not isinstance(params, dict):
            if "id" in message:
                self.reply(request_id, error={"code": -32600, "message": "invalid request"})
            return None
        if method == "notifications/cancelled":
            self.cancel(params.get("requestId"))
            return None
        if method.startswith("notifications/"):
            return None
        if method == "initialize":
            requested = params.get("protocolVersion")
            self.reply(request_id, {
                "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "fixer", "version": VERSION},
                "instructions": self.instructions(),
            })
        elif method == "ping":
            self.reply(request_id, {})
        elif method == "tools/list":
            self.reply(request_id, {"tools": self.tools()})
        elif method == "tools/call":
            with self.calls_lock:
                self.calls[request_id] = None
            thread = threading.Thread(target=self.call_tool, args=(request_id, params), daemon=True)
            thread.start()
            return thread
        else:
            self.reply(request_id, error={"code": -32601, "message": f"unknown method {method}"})
        return None

    # tools

    def instructions(self) -> str:
        if self.inside_member:
            return "Fixer offers no tools inside a Team member."
        return (f'Team "{self.team.name}". Each tool runs one member with its own model and '
                "returns its answer to you. A member's answer is a claim, not a verified fact: "
                "check it before you act on it or repeat it.")

    def callable(self) -> tuple[str, ...]:
        return () if self.inside_member else tuple(self.team.members)

    def tools(self) -> list[dict]:
        tools = []
        for member_id in self.callable():
            member = self.team.members[member_id]
            if member.kind == "peer":
                memory = "Peer: remembers your earlier calls to it in this session; send only what is new."
            else:
                memory = "Starts fresh on every call: include everything it needs."
            access = "read-only" if member.read_only else "may edit files"
            tools.append({
                "name": member_id,
                "description": f"{member.description}\n{memory} Model {member.model}, {access}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "What you want from this member."},
                        "context": {"type": "string", "description": "What the member needs that it cannot find in the workspace or remember: findings, diffs, constraints."},
                    },
                    "required": ["task"],
                    "additionalProperties": False,
                },
            })
        return tools

    def call_tool(self, request_id, params: dict) -> None:
        try:
            text, is_error = self.consult(request_id, params)
        except Exception as err:  # never leave a request unanswered
            text, is_error = f"fixer: {err}", True
        with self.calls_lock:
            self.calls.pop(request_id, None)
            if request_id in self.cancelled:
                self.cancelled.discard(request_id)
                return  # cancelled requests get no response
        self.reply(request_id, {"content": [{"type": "text", "text": text}], "isError": is_error})

    def consult(self, request_id, params: dict) -> tuple[str, bool]:
        member_id = params.get("name", "")
        args = params.get("arguments") or {}
        if member_id not in self.callable():
            return f"fixer: no Team member '{member_id}' here", True
        task = args.get("task")
        if not isinstance(task, str) or not task.strip():
            return "fixer: 'task' is required", True
        context = args.get("context", "")
        if not isinstance(context, str):
            return "fixer: 'context' must be a string", True
        member = self.team.members[member_id]
        if member.kind == "peer":
            with self.peer_locks[member_id]:
                return self.run(request_id, member, task, context, keep=True)
        return self.run(request_id, member, task, context, keep=False)

    def run(self, request_id, member: Member, task: str, context: str, keep: bool) -> tuple[str, bool]:
        adapter = self.team.adapter(member)
        timeout = member.timeout_seconds or self.team.timeout_seconds
        # Members work in this server's directory. Some CLIs (OpenCode) trust
        # $PWD over the real working directory, so set both.
        workspace = os.getcwd()
        env = {**os.environ, **self.team.env, "FIXER_MEMBER": member.id, "PWD": workspace}

        session = self.sessions.get(member.id) if keep else None
        resume = session is not None
        prompt = (next_prompt(task, context) if resume
                  else first_prompt(self.team, member, task, context))

        slot = self.slots.acquire(member.id)
        if slot is None:
            return (f"fixer: {self.team.max_active} members are already running for this team; "
                    "wait for one to finish or raise max_active"), True
        prompt_file = None
        started = time.monotonic()
        try:
            if keep and not resume:
                session = adapter.new_session(member, env)
            call = Call(member, prompt, session, resume, keep, timeout)
            invocation = adapter.invoke(call)
            if invocation.stdin is None and len(prompt.encode()) > MAX_ARG_PROMPT:
                prompt_file = tempfile.NamedTemporaryFile("w", prefix="fixer-task-", suffix=".md", delete=False)
                prompt_file.write(prompt)
                prompt_file.close()
                call.prompt = (f"Your full request is in the file {prompt_file.name}. "
                               "Read all of it first, then do what it asks.")
                invocation = adapter.invoke(call)
            try:
                process = subprocess.Popen(
                    invocation.argv,
                    stdin=subprocess.PIPE if invocation.stdin is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env={**env, **invocation.env}, cwd=workspace, text=True,
                    start_new_session=True)
            except OSError as err:
                return f"fixer: could not start {member.id} ({invocation.argv[0]}): {err.strerror}", True
            with self.calls_lock:
                self.calls[request_id] = process
                cancelled_early = request_id in self.cancelled
            if cancelled_early:
                _kill(process)
            try:
                stdout, stderr = process.communicate(invocation.stdin, timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill(process)
                process.communicate()
                return f"fixer: {member.id} did not finish within {timeout}s", True
        except MemberError as err:
            return f"fixer: {member.id}: {err}", True
        finally:
            ActiveSlots.release(slot)
            if prompt_file:
                os.unlink(prompt_file.name)

        elapsed = time.monotonic() - started
        header = f"[{member.id} · {member.runner} {member.model} · {elapsed:.0f}s]"
        try:
            answer, new_session = adapter.parse(stdout, call)
            failure = None
        except Exception as err:  # output Fixer cannot read is a member failure
            answer, new_session, failure = "", None, str(err) or type(err).__name__
        if process.returncode != 0:
            failure = f"exit status {process.returncode}" + (f" ({failure})" if failure else "")
        if failure is None and not answer.strip():
            failure = "no answer"
        log_event(member=member.id, runner=member.runner, model=member.model,
                  resumed=resume, seconds=round(elapsed, 1), exit_status=process.returncode,
                  ok=failure is None)
        if failure:
            detail = (stderr.strip() or stdout.strip())[-2000:]
            return f"{header} failed: {failure}\n{detail}", True
        if keep and new_session:
            self.sessions[member.id] = new_session
        return f"{header}\n{answer.strip()}", False

    def cancel(self, request_id) -> None:
        with self.calls_lock:
            if request_id not in self.calls:
                return
            self.cancelled.add(request_id)
            process = self.calls[request_id]
        if process is not None:
            _kill(process)

    def cancel_all(self) -> None:
        with self.calls_lock:
            pending = list(self.calls)
        for request_id in pending:
            self.cancel(request_id)


def describe(team: Team) -> str:
    lines = [f"Team {team.name} ({team.path})",
             f"max_active={team.max_active} timeout={team.timeout_seconds}s"]
    for member in team.members.values():
        access = "read-only" if member.read_only else "writes"
        lines.append(f"  {member.id}: {member.kind}, {member.runner} {member.model}, {access}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fixer", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the MCP server on stdio")
    serve.add_argument("--team", help="Team file (default: $FIXER_TEAM, .fixer/team.toml, fixer.toml)")
    check = sub.add_parser("check", help="validate a Team file and print its roster")
    check.add_argument("--team")
    args = parser.parse_args(argv)

    try:
        team = load_team(find_team(args.team))
        if args.command == "check":
            print(describe(team))
            return 0
    except TeamError as err:
        print(f"fixer: {err}", file=sys.stderr)
        return 2
    Server(team).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
