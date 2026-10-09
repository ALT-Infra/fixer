"""Unit tests. Parsers run against real CLI output saved in tests/fixtures.

Server behavior uses a stand-in CLI (fake_member.py) that can keep a
session. These tests prove the protocol, the Team rules, and the limits.
tests/test_live.py proves that each runner works with a real model.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
FAKE = str(ROOT / "tests" / "fake_member.py")
sys.path.insert(0, str(ROOT))
import fixer  # noqa: E402


class FakeAdapter(fixer.Adapter):
    name = "fake"
    sessions = True
    takes_effort = True

    def check_effort(self, model, effort, env, deadline):
        if effort == "slow":
            time.sleep(1.5)
        return f"the fake CLI refuses effort '{effort}'" if effort == "bad" else None

    def invoke(self, call):
        argv = [sys.executable, FAKE, call.member.model]
        if call.resume:
            argv += ["--resume", call.session]
        elif call.keep:
            argv += ["--new"]
        if not call.member.read_only:
            argv += ["--writes"]
        return fixer.Invocation(argv, stdin=call.prompt)

    def parse(self, stdout, call):
        result = json.loads(stdout)
        return result["answer"], result["session"]


fixer.ADAPTERS["fake"] = FakeAdapter()

TEAM = """
name = "test"

[members.reviewer]
kind = "peer"
runner = "fake"
model = "model-a"
description = "Reviews changes."
instructions = "Be blunt."

[members.scout]
kind = "specialist"
runner = "fake"
model = "model-b"
description = "Finds things."
"""


def write_team(directory: Path, body: str) -> Path:
    path = directory / "team.toml"
    path.write_text(textwrap.dedent(body))
    return path


def call(member, model="m", read_only=True, kind="specialist", effort=""):
    return fixer.Member(id=member, kind=kind, runner="x", model=model, description="d", read_only=read_only,
                        effort=effort)


class TeamFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def load(self, body):
        return fixer.load_team(write_team(self.dir, body))

    def rejected(self, body, fragment):
        with self.assertRaises(fixer.TeamError) as caught:
            self.load(body)
        self.assertIn(fragment, str(caught.exception))

    def test_team_loads(self):
        team = self.load(TEAM)
        self.assertEqual(team.members["reviewer"].kind, "peer")
        self.assertTrue(team.members["scout"].read_only)

    def test_unknown_keys_are_rejected(self):
        self.rejected(TEAM.replace('model = "model-b"', 'model = "model-b"\nconsults = ["reviewer"]'),
                      "unknown key(s) consults")

    def test_kind_is_required_and_checked(self):
        self.rejected(TEAM.replace('kind = "specialist"\n', ""), "missing 'kind'")
        self.rejected(TEAM.replace('kind = "specialist"', 'kind = "boss"'), "'peer' or 'specialist'")

    def test_unknown_runner_names_the_known_ones(self):
        self.rejected(TEAM.replace('runner = "fake"\nmodel = "model-b"', 'runner = "nope"\nmodel = "model-b"'),
                      "known: claude, cline, codex, cursor, fake, fx, opencode")

    def test_a_peer_needs_a_runner_that_can_resume(self):
        self.rejected('[members.p]\nkind = "peer"\nrunner = "cline"\nmodel = "m"\ndescription = "d"\n',
                      "can run specialists only")

    def test_custom_commands_run_read_only_specialists(self):
        team = self.load('[commands]\nmine = ["my-cli", "--model", "{model}"]\n'
                         '[members.s]\nkind = "specialist"\nrunner = "mine"\nmodel = "m"\ndescription = "d"\n')
        self.assertEqual(team.adapter(team.members["s"]).template, ("my-cli", "--model", "{model}"))
        self.rejected('[commands]\nmine = ["my-cli"]\n'
                      '[members.s]\nkind = "specialist"\nrunner = "mine"\nmodel = "m"\ndescription = "d"\nread_only = false\n',
                      "has no write mode")
        self.rejected('[commands]\nclaude = ["x"]\n[members.s]\nkind = "specialist"\nrunner = "claude"\nmodel = "m"\ndescription = "d"\n',
                      "built-in runner")

    def test_ids(self):
        self.rejected('[members.primary]\nkind = "specialist"\nrunner = "fake"\nmodel = "m"\ndescription = "d"\n', "host agent")
        self.rejected('[members.Bad]\nkind = "specialist"\nrunner = "fake"\nmodel = "m"\ndescription = "d"\n', "lowercase")
        self.load('[members.engineering_checkup]\nkind = "specialist"\nrunner = "fake"\nmodel = "m"\ndescription = "d"\n')

    def test_effort_is_checked_by_the_cli_or_passed_to_it(self):
        member = '[members.m]\nkind = "specialist"\nrunner = "{runner}"\nmodel = "m"\ndescription = "d"\neffort = "{effort}"\n'
        # Codex and Cline refuse an unknown effort themselves, when the member runs.
        self.assertEqual(self.load(member.format(runner="codex", effort="ultra")).members["m"].effort, "ultra")
        self.assertEqual(self.load(member.format(runner="cline", effort="ultra")).members["m"].effort, "ultra")
        self.rejected(member.format(runner="fx", effort="high"), "runner 'fx' has no effort setting")
        self.rejected(member.format(runner="codex", effort=" "), "'effort' must be a non-empty string")
        self.rejected('[commands]\nmine = ["my-cli"]\n' + member.format(runner="mine", effort="high"),
                      "runner 'mine' has no effort setting")
        self.assertEqual(self.load(TEAM).members["scout"].effort, "")

    def stand_in(self, name, body):
        """A stand-in CLI on an otherwise empty PATH, for this test."""
        bin_dir = Path(tempfile.mkdtemp())
        (bin_dir / name).write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
        (bin_dir / name).chmod(0o755)
        path = os.environ["PATH"]
        os.environ["PATH"] = str(bin_dir)
        self.addCleanup(os.environ.__setitem__, "PATH", path)
        return bin_dir / name

    def test_claude_is_asked_about_the_effort(self):
        # Like `claude --version`, it warns about an effort it does not know.
        claude = self.stand_in("claude", """\
            import sys
            args = sys.argv[1:]
            value = args[args.index("--effort") + 1] if "--effort" in args else None
            if value == "broken":
                sys.exit(2)
            if value not in (None, "low", "max"):
                print(f"Warning: Unknown --effort value '{value}'", file=sys.stderr)
            print("9.9.9 (Claude Code)", file=sys.stderr)
            """)
        member = '[members.m]\nkind = "specialist"\nrunner = "claude"\nmodel = "m"\ndescription = "d"\neffort = "{}"\n'
        self.assertEqual(self.load(member.format("max")).members["m"].effort, "max")
        self.rejected(member.format("xhgh"), "claude refuses effort 'xhgh': Warning: Unknown --effort value 'xhgh'")
        self.rejected(member.format("broken"), "Fixer cannot check the effort: 'claude --effort broken --version' "
                                               "failed with exit status 2")
        claude.write_text(f"#!{sys.executable}\nprint('9.9.9 (Claude Code)')\n")  # warns about nothing
        self.rejected(member.format("max"), "claude no longer warns about an unknown --effort value")
        claude.unlink()
        self.rejected(member.format("max"), "Fixer cannot check the effort: claude is not installed")

    def test_opencode_effort_is_a_variant_of_the_model(self):
        variants = fixer.OpenCodeAdapter.variants
        listing = (FIXTURES / "opencode-models.txt").read_text()  # real `opencode models --verbose` output
        self.assertEqual(variants(listing, "opencode/step-5-preview-free"), ["low", "medium", "high"])
        self.assertEqual(variants(listing, "opencode/nemotron-3.5-lightning-free"), [])
        self.assertIsNone(variants(listing, "opencode/step-5"))
        with self.assertRaises(ValueError):  # another shape is not "no variants"
            variants(listing.replace('"variants"', '"modes"'), "opencode/step-5-preview-free")
        self.stand_in("opencode", f"print({listing.replace(chr(34) + 'variants' + chr(34), chr(34) + 'modes' + chr(34))!r})\n")
        member = ('[members.m]\nkind = "specialist"\nrunner = "opencode"\nmodel = "opencode/step-5-preview-free"\n'
                  'description = "d"\neffort = "high"\n')
        self.rejected(member, "Fixer cannot check the effort: it cannot read 'opencode models --verbose'")
        os.environ["PATH"] = tempfile.mkdtemp()  # no opencode on it
        self.rejected(member, "Fixer cannot check the effort: opencode is not installed")

    def test_example_team_is_valid(self):
        team = fixer.load_team(ROOT / "team.example.toml")
        self.assertEqual({m.kind for m in team.members.values()}, {"peer", "specialist"})


class AdapterTests(unittest.TestCase):
    """Command lines for each mode, and parsing of real CLI output."""

    def invoke(self, name, member, session=None, resume=False, keep=False):
        c = fixer.Call(member, "PROMPT", session, resume, keep, 60)
        return fixer.ADAPTERS[name].invoke(c), c

    def test_claude(self):
        adapter = fixer.ADAPTERS["claude"]
        one, _ = self.invoke("claude", call("s"))
        self.assertIn("--no-session-persistence", one.argv)
        self.assertEqual(one.stdin, "PROMPT")
        first, _ = self.invoke("claude", call("p", read_only=False), session="u-1", keep=True)
        self.assertEqual(first.argv[first.argv.index("--session-id") + 1], "u-1")
        self.assertIn("acceptEdits", first.argv)
        later, c = self.invoke("claude", call("p"), session="u-1", resume=True, keep=True)
        self.assertEqual(later.argv[later.argv.index("--resume") + 1], "u-1")
        self.assertNotIn("--effort", one.argv + later.argv)
        self.assertNotIn("CLAUDE_CODE_EFFORT_LEVEL", one.env)
        for session, resume in ((None, False), ("u-1", True)):
            pinned, _ = self.invoke("claude", call("p", effort="xhigh"), session=session, resume=resume, keep=resume)
            self.assertEqual(pinned.argv[pinned.argv.index("--effort") + 1], "xhigh")
            self.assertEqual(pinned.env["CLAUDE_CODE_EFFORT_LEVEL"], "xhigh")
        self.assertEqual(adapter.parse((FIXTURES / "claude.json").read_text(), c),
                         ("PONG", "11111111-2222-4333-8444-555555555555"))
        with self.assertRaises(fixer.MemberError):
            adapter.parse('{"type":"result","is_error":true,"result":"Credit balance is too low"}', c)

    def test_codex(self):
        one, c = self.invoke("codex", call("s"))
        self.assertEqual(one.argv[:2], ["codex", "exec"])
        self.assertIn("--ephemeral", one.argv)
        self.assertIn('sandbox_mode="read-only"', one.argv)
        self.assertEqual((one.argv[-1], one.stdin), ("-", "PROMPT"))
        later, _ = self.invoke("codex", call("p", read_only=False), session="t-1", resume=True, keep=True)
        self.assertEqual(later.argv[:3], ["codex", "exec", "resume"])
        self.assertEqual(later.argv[-2:], ["t-1", "-"])
        self.assertIn('sandbox_mode="workspace-write"', later.argv)
        self.assertNotIn("--ephemeral", later.argv)
        self.assertFalse(any("model_reasoning_effort" in part for part in one.argv + later.argv))
        for session, resume in ((None, False), ("t-1", True)):
            pinned, _ = self.invoke("codex", call("p", effort="xhigh"), session=session, resume=resume, keep=resume)
            self.assertIn('model_reasoning_effort="xhigh"', pinned.argv)
            self.assertEqual(pinned.argv[pinned.argv.index('model_reasoning_effort="xhigh"') - 1], "-c")
        answer, thread = fixer.ADAPTERS["codex"].parse((FIXTURES / "codex.jsonl").read_text(), c)
        self.assertEqual((answer, thread), ("PONG", "01a1087e-6692-7d61-8d78-a9569f645292"))

    def test_opencode(self):
        one, c = self.invoke("opencode", call("s"))
        self.assertEqual(one.argv[-1], "PROMPT")
        self.assertEqual(one.argv[one.argv.index("--agent") + 1], "plan")
        later, _ = self.invoke("opencode", call("p", read_only=False), session="ses_1", resume=True, keep=True)
        self.assertEqual(later.argv[later.argv.index("--session") + 1], "ses_1")
        self.assertNotIn("--agent", later.argv)
        self.assertNotIn("--variant", one.argv + later.argv)
        pinned, _ = self.invoke("opencode", call("p", effort="high"), session="ses_1", resume=True, keep=True)
        self.assertEqual(pinned.argv[pinned.argv.index("--variant") + 1], "high")
        self.assertEqual(pinned.argv[-1], "PROMPT")
        answer, session = fixer.ADAPTERS["opencode"].parse((FIXTURES / "opencode.jsonl").read_text(), c)
        self.assertEqual(answer, "ZEBRA-41")
        self.assertTrue(session.startswith("ses_"))

    def test_cline(self):
        one, c = self.invoke("cline", call("s"))
        self.assertIn("--plan", one.argv)
        write, _ = self.invoke("cline", call("w", read_only=False))
        self.assertEqual(write.argv[write.argv.index("--auto-approve") + 1], "true")
        self.assertNotIn("--thinking", one.argv + write.argv)
        pinned, _ = self.invoke("cline", call("s", effort="xhigh"))
        self.assertEqual(pinned.argv[pinned.argv.index("--thinking") + 1], "xhigh")
        self.assertEqual(pinned.argv[-1], "PROMPT")
        self.assertEqual(fixer.ADAPTERS["cline"].parse((FIXTURES / "cline.jsonl").read_text(), c), ("OK", None))
        with self.assertRaises(fixer.MemberError):
            fixer.ADAPTERS["cline"].parse('{"type":"error","message":"Free model promotion ended"}', c)

    def test_fx(self):
        one, c = self.invoke("fx", call("s"))
        self.assertIn("--no-save", one.argv)
        later, _ = self.invoke("fx", call("p", read_only=False), session="abc", resume=True, keep=True)
        self.assertEqual(later.argv[later.argv.index("--resume-id") + 1], "abc")
        self.assertIn("--auto", later.argv)
        self.assertEqual(fixer.ADAPTERS["fx"].parse((FIXTURES / "fx.json").read_text(), c), ("OK", "ncWnEvfmiGsE"))

    def test_cursor(self):
        one, c = self.invoke("cursor", call("s"))
        self.assertEqual(one.argv[one.argv.index("--mode") + 1], "ask")
        later, _ = self.invoke("cursor", call("p", read_only=False), session="chat-1", resume=True, keep=True)
        self.assertEqual(later.argv[later.argv.index("--resume") + 1], "chat-1")
        self.assertIn("--force", later.argv)
        self.assertEqual(fixer.ADAPTERS["cursor"].parse((FIXTURES / "cursor.json").read_text(), c),
                         ("PONG", "af4c9f09-bffa-4fc1-9dd7-bc8eb578e976"))


class Harness:
    """Drives a Server in-process over line-delimited JSON-RPC."""

    def __init__(self, team):
        read_fd, write_fd = os.pipe()
        self.to_server = os.fdopen(write_fd, "w")
        self.from_host = os.fdopen(read_fd)
        self.out = io.StringIO()
        self.lock = threading.Lock()
        self.server = fixer.Server(team, out=self)
        self.thread = threading.Thread(target=self.server.serve, args=(self.from_host,), daemon=True)
        self.thread.start()
        self.next_id = 0

    def write(self, text):
        with self.lock:
            self.out.write(text)

    def flush(self):
        pass

    def messages(self):
        with self.lock:
            return [json.loads(line) for line in self.out.getvalue().splitlines() if line]

    def send(self, method, params=None, notify=False):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notify:
            self.next_id += 1
            message["id"] = self.next_id
        self.to_server.write(json.dumps(message) + "\n")
        self.to_server.flush()
        return message.get("id")

    def wait(self, request_id, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for message in self.messages():
                if message.get("id") == request_id:
                    return message
            time.sleep(0.02)
        raise AssertionError(f"no response to {request_id}")

    def call(self, name, **arguments):
        return self.wait(self.send("tools/call", {"name": name, "arguments": arguments}))["result"]

    def text(self, name, **arguments):
        result = self.call(name, **arguments)
        return result["content"][0]["text"], result["isError"]

    def close(self):
        self.to_server.close()
        self.thread.join(timeout=10)
        self.from_host.close()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()).resolve()
        (self.dir / "sessions").mkdir()
        self.env = {"FIXER_RUN_DIR": str(self.dir / "run"), "FAKE_SESSIONS": str(self.dir / "sessions")}
        os.environ.update(self.env)
        os.environ.pop("FIXER_MEMBER", None)
        self.harness = None

    def start(self, body=TEAM):
        self.harness = Harness(fixer.load_team(write_team(self.dir, body)))
        return self.harness

    def tearDown(self):
        if self.harness:
            self.harness.close()
        for name in self.env:
            os.environ.pop(name, None)

    def test_initialize_negotiates_protocol_version(self):
        h = self.start()
        self.assertEqual(h.wait(h.send("initialize", {"protocolVersion": "2025-03-26"}))["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(h.wait(h.send("initialize", {"protocolVersion": "1999"}))["result"]["protocolVersion"],
                         fixer.PROTOCOL_VERSIONS[0])

    def test_one_tool_per_member_and_kind_in_description(self):
        h = self.start()
        tools = {t["name"]: t for t in h.wait(h.send("tools/list"))["result"]["tools"]}
        self.assertEqual(set(tools), {"reviewer", "scout"})
        self.assertIn("remembers your earlier calls", tools["reviewer"]["description"])
        self.assertIn("Starts fresh on every call", tools["scout"]["description"])
        self.assertIn("read-only", tools["scout"]["description"])

    def serve(self, body):
        self.harness = Harness(fixer.load_team(write_team(self.dir, body), check_efforts=False))
        return self.harness

    def test_a_running_server_checks_an_effort_at_each_call(self):
        body = TEAM.replace('instructions = "Be blunt."', 'instructions = "Be blunt."\neffort = "bad"')
        with self.assertRaises(fixer.TeamError):  # `fixer check` asks at once
            fixer.load_team(write_team(self.dir, body))
        h = self.serve(body)
        for _ in range(2):  # no answer is kept: the CLI can change while the server runs
            self.assertEqual(h.text("reviewer", task="Look."), ("fixer: reviewer: the fake CLI refuses effort 'bad'", True))
        text, is_error = h.text("scout", task="Look.")  # the other members still work
        self.assertFalse(is_error, text)

    def test_the_effort_check_counts_in_the_calls_time_limit(self):
        h = self.serve(TEAM.replace('instructions = "Be blunt."', 'instructions = "Be blunt."\neffort = "slow"\ntimeout_seconds = 1'))
        text, is_error = h.text("reviewer", task="Look.")
        self.assertTrue(is_error)
        self.assertIn("did not finish within 1s", text)

    def test_the_effort_check_waits_for_a_free_slot(self):
        h = self.serve("max_active = 1\n" + TEAM.replace('instructions = "Be blunt."', 'instructions = "Be blunt."\neffort = "bad"'))
        busy = h.send("tools/call", {"name": "scout", "arguments": {"task": "SLEEP 2"}})
        time.sleep(0.5)
        text, is_error = h.text("reviewer", task="Look.")
        self.assertTrue(is_error)
        self.assertIn("members are already running", text)  # not the effort: it has no slot yet
        h.wait(busy)

    def test_effort_shows_in_the_description_the_answer_and_the_log(self):
        log = self.dir / "calls.log"
        os.environ["FIXER_LOG"] = str(log)
        self.addCleanup(os.environ.pop, "FIXER_LOG", None)
        h = self.start(TEAM.replace('instructions = "Be blunt."', 'instructions = "Be blunt."\neffort = "high"'))
        tools = {t["name"]: t for t in h.wait(h.send("tools/list"))["result"]["tools"]}
        self.assertIn("Model model-a, effort high, read-only.", tools["reviewer"]["description"])
        self.assertIn("Model model-b, read-only.", tools["scout"]["description"])
        text, is_error = h.text("reviewer", task="Look.")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("[reviewer · fake model-a, effort high · "), text)
        h.text("scout", task="Look.")
        calls = {entry["member"]: entry for entry in map(json.loads, log.read_text().splitlines())}
        self.assertEqual((calls["reviewer"]["effort"], calls["scout"]["effort"]), ("high", None))

    def test_specialist_call_carries_role_task_context_and_workspace(self):
        h = self.start()
        text, is_error = h.text("scout", task="Find the parser.", context="It reads TOML.")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("[scout · fake model-b · "))
        for expected in ("Find the parser.", "It reads TOML.", "Do not modify files", "member=scout",
                         f"cwd={os.getcwd()} pwd={os.getcwd()}"):
            self.assertIn(expected, text)

    def test_peer_keeps_its_session_and_specialist_does_not(self):
        h = self.start()
        first, _ = h.text("reviewer", task="first")
        self.assertIn("remembered= ", first)
        self.assertIn("This is the start of your conversation", first)
        second, _ = h.text("reviewer", task="second")
        self.assertIn("remembered=first ", second)
        self.assertIn("A new request from the primary", second)
        h.text("scout", task="alpha")
        fresh, _ = h.text("scout", task="beta")
        self.assertIn("remembered= ", fresh)

    def test_parallel_calls_to_one_peer_take_turns(self):
        h = self.start()
        ids = [h.send("tools/call", {"name": "reviewer", "arguments": {"task": f"SLEEP 0.5 call-{n}"}}) for n in (1, 2)]
        texts = [h.wait(i)["result"]["content"][0]["text"] for i in ids]
        self.assertEqual(sum("remembered=SLEEP 0.5 call-" in t for t in texts), 1, texts)

    def test_different_members_run_in_parallel(self):
        h = self.start()
        started = time.monotonic()
        ids = [h.send("tools/call", {"name": n, "arguments": {"task": "SLEEP 1"}}) for n in ("reviewer", "scout")]
        for i in ids:
            self.assertFalse(h.wait(i)["result"]["isError"])
        self.assertLess(time.monotonic() - started, 1.9)

    def test_failures_are_tool_errors(self):
        h = self.start()
        text, is_error = h.text("scout", task="FAIL")
        self.assertTrue(is_error)
        self.assertIn("exit status 3", text)
        self.assertIn("deliberate failure", text)
        text, is_error = h.text("scout", task="SILENT")
        self.assertTrue(is_error)
        self.assertIn("no answer", text)
        self.assertTrue(h.text("ghost", task="x")[1])
        self.assertTrue(h.text("scout", task="  ")[1])

    def test_a_peer_without_a_session_id_fails_instead_of_forgetting(self):
        h = self.start()
        text, is_error = h.text("reviewer", task="NOSESSION Look.")
        self.assertTrue(is_error)
        self.assertIn("the CLI gave no session id, so this peer would not remember the call", text)
        text, is_error = h.text("scout", task="NOSESSION Look.")  # a specialist keeps no session anyway
        self.assertFalse(is_error, text)

    def test_a_failed_first_call_does_not_keep_a_session(self):
        h = self.start()
        self.assertTrue(h.text("reviewer", task="FAIL")[1])
        text, _ = h.text("reviewer", task="again")
        self.assertIn("This is the start of your conversation", text)

    def test_cancellation_kills_the_member_and_sends_no_response(self):
        h = self.start()
        request_id = h.send("tools/call", {"name": "scout", "arguments": {"task": "SLEEP 30"}})
        time.sleep(0.5)
        h.send("notifications/cancelled", {"requestId": request_id}, notify=True)
        time.sleep(1)
        self.assertEqual(h.wait(h.send("ping"))["result"], {})
        self.assertFalse(any(m.get("id") == request_id for m in h.messages()))
        self.assertFalse(list((self.dir / "run").rglob("*.slot")))

    def test_timeout(self):
        h = self.start(TEAM.replace('model = "model-b"', 'model = "model-b"\ntimeout_seconds = 1'))
        text, is_error = h.text("scout", task="SLEEP 10")
        self.assertTrue(is_error)
        self.assertIn("did not finish within 1s", text)

    def test_max_active(self):
        h = self.start("max_active = 1\n" + TEAM)
        slow = h.send("tools/call", {"name": "reviewer", "arguments": {"task": "SLEEP 2"}})
        time.sleep(0.5)
        text, is_error = h.text("scout", task="hello")
        self.assertTrue(is_error)
        self.assertIn("already running", text)
        self.assertFalse(h.wait(slow)["result"]["isError"])

    def test_writes_flag(self):
        h = self.start(TEAM.replace('model = "model-b"', 'model = "model-b"\nread_only = false'))
        text, _ = h.text("scout", task="hello")
        self.assertIn("writes=True", text)
        self.assertNotIn("Do not modify files", text)

    def test_no_tools_inside_a_member(self):
        os.environ["FIXER_MEMBER"] = "reviewer"
        try:
            h = self.start()
            self.assertEqual(h.wait(h.send("tools/list"))["result"]["tools"], [])
            self.assertTrue(h.text("scout", task="x")[1])
        finally:
            os.environ.pop("FIXER_MEMBER", None)

    def test_long_prompts_go_through_a_file_for_argv_runners(self):
        body = ('[commands]\nargv = ["' + sys.executable + '", "-c", "import sys; print(sys.argv[1][:300])", "{prompt}"]\n'
                '[members.s]\nkind = "specialist"\nrunner = "argv"\nmodel = "m"\ndescription = "d"\n')
        h = self.start(body)
        text, is_error = h.text("s", task="t", context="x" * (200 * 1024))
        self.assertFalse(is_error, text)
        self.assertIn("Your full request is in the file", text)

    def test_malformed_requests_do_not_stop_the_server(self):
        h = self.start()
        h.to_server.write('not json\n{"jsonrpc":"2.0","id":7,"method":5}\n'
                          '{"jsonrpc":"2.0","id":8,"method":"tools/list","params":[]}\n')
        h.to_server.flush()
        self.assertEqual(h.wait(7)["error"]["code"], -32600)
        self.assertEqual(h.wait(8)["error"]["code"], -32600)
        self.assertEqual(h.wait(h.send("resources/list"))["error"]["code"], -32601)
        self.assertEqual(h.wait(h.send("ping"))["result"], {})


class CommandLineTests(unittest.TestCase):
    def test_check(self):
        good = subprocess.run([sys.executable, str(ROOT / "fixer.py"), "check", "--team", str(ROOT / "team.example.toml")],
                              capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn("reviewer: peer, codex", good.stdout)
        bad = subprocess.run([sys.executable, str(ROOT / "fixer.py"), "check", "--team", "/nonexistent/team.toml"],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("no Team file at /nonexistent/team.toml. Fixer reads --team, then $FIXER_TEAM", bad.stderr)
        with tempfile.TemporaryDirectory() as empty:
            chosen = subprocess.run([sys.executable, str(ROOT / "fixer.py"), "check"], capture_output=True, text=True,
                                    cwd=empty, env={**os.environ, "FIXER_TEAM": str(ROOT / "team.example.toml")})
            self.assertEqual(chosen.returncode, 0, chosen.stderr)
            self.assertIn(f"({ROOT / 'team.example.toml'})", chosen.stdout)
            unset = subprocess.run([sys.executable, str(ROOT / "fixer.py"), "check"], capture_output=True, text=True,
                                   cwd=empty, env={k: v for k, v in os.environ.items() if k != "FIXER_TEAM"})
            self.assertEqual(unset.returncode, 2)
            self.assertIn("no Team file at .fixer/team.toml", unset.stderr)


if __name__ == "__main__":
    unittest.main()
