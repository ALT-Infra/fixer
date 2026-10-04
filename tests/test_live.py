"""Live tests: every check here runs a real CLI on a real model.

Skipped unless FIXER_LIVE names the runners to test, for example
FIXER_LIVE=claude,codex. Give each runner's model in FIXER_LIVE_<RUNNER>,
for example FIXER_LIVE_CODEX=gpt-6-luna. The CLIs must be installed and
signed in. Answers vary between runs, so the checks look at structure and
at exact tokens the prompts ask for, not at wording.

For each runner:
- one-time call (a specialist) returns an answer;
- a peer keeps its session with the primary: a second call recalls a code
  word from the first, and a specialist on the same model does not;
- a read-only member does not create a file; a writing member does.
"""

import io
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

import fixer

RUNNERS = [name for name in os.environ.get("FIXER_LIVE", "").split(",") if name]


def make_team(directory: Path, runner: str, model: str) -> fixer.Team:
    body = textwrap.dedent(f"""
        name = "live"
        [members.peer]
        kind = "peer"
        runner = "{runner}"
        model = "{model}"
        description = "Test peer."

        [members.solo]
        kind = "specialist"
        runner = "{runner}"
        model = "{model}"
        description = "Test specialist."

        [members.writer]
        kind = "specialist"
        runner = "{runner}"
        model = "{model}"
        description = "Test writer."
        read_only = false
        """)
    if runner == "cline":  # Cline cannot resume headless: no peers.
        body = body.replace('kind = "peer"', 'kind = "specialist"')
    path = directory / ".fixer" / "team.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return fixer.load_team(path)


class Live(unittest.TestCase):
    def call(self, server, member, task):
        text, is_error = server.consult(None, {"name": member, "arguments": {"task": task}})
        print(f"\n--- {member}: error={is_error}\n{text[:600]}")
        return text, is_error


def _make(runner: str):
    model = os.environ.get(f"FIXER_LIVE_{runner.upper()}", "")

    def setUp(self):
        if not model:
            self.skipTest(f"set FIXER_LIVE_{runner.upper()}")
        self.workspace = Path(tempfile.mkdtemp(prefix=f"fixer-live-{runner}-")).resolve()
        self.cwd = os.getcwd()
        os.chdir(self.workspace)
        os.environ["FIXER_RUN_DIR"] = str(self.workspace / ".run")
        self.team = make_team(self.workspace, runner, model)
        self.server = fixer.Server(self.team, out=io.StringIO())

    def tearDown(self):
        os.chdir(self.cwd)

    def test_one_time_call(self):
        text, is_error = self.call(self.server, "solo", "Reply with exactly: PONG-1")
        self.assertFalse(is_error, text)
        self.assertIn("PONG-1", text)

    def test_peer_keeps_its_session_and_specialist_does_not(self):
        if self.team.members["peer"].kind != "peer":
            self.skipTest(f"{runner} cannot resume a session headless")
        text, is_error = self.call(self.server, "peer", "Remember the code word ZEBRA-41. Reply only with OK.")
        self.assertFalse(is_error, text)
        text, is_error = self.call(self.server, "peer", "What was the code word? Reply only with the word.")
        self.assertFalse(is_error, text)
        self.assertIn("ZEBRA-41", text)
        self.call(self.server, "solo", "Remember the code word ZEBRA-41. Reply only with OK.")
        text, _ = self.call(self.server, "solo", "What was the code word? Reply only with the word, or NONE.")
        self.assertNotIn("ZEBRA-41", text)

    def test_read_only_and_write_modes(self):
        self.call(self.server, "solo", "Create a file named ro.txt that contains HELLO. Then reply DONE.")
        self.assertFalse((self.workspace / "ro.txt").exists(), "a read-only member created a file")
        text, is_error = self.call(self.server, "writer", "Create a file named rw.txt that contains HELLO. Then reply DONE.")
        self.assertFalse(is_error, text)
        self.assertTrue((self.workspace / "rw.txt").exists(), "a writing member did not create the file")

    return type(f"Live_{runner}", (Live,), {
        "setUp": setUp, "tearDown": tearDown,
        "test_one_time_call": test_one_time_call,
        "test_peer_keeps_its_session_and_specialist_does_not": test_peer_keeps_its_session_and_specialist_does_not,
        "test_read_only_and_write_modes": test_read_only_and_write_modes,
    })


for _runner in RUNNERS:
    globals()[f"Live_{_runner}"] = _make(_runner)

if not RUNNERS:
    class LiveSkipped(unittest.TestCase):
        @unittest.skip("set FIXER_LIVE=<runner,...> to run against real models")
        def test_live(self):
            pass


if __name__ == "__main__":
    unittest.main()
