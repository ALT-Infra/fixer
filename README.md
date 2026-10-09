# Fixer

Fixer gives your coding agent a Team of models from other providers.

Fixer is an MCP server. You write a Team file. Each member of the Team has
a CLI, a model, and a role. Your agent gets one tool for each member. When
your agent calls a tool, Fixer runs that member through the member's CLI,
on the member's model, in your workspace. Fixer then gives the member's
answer to your agent.

```
you ─► host (for example Claude Code; its model is the primary)
         │ calls the tool "reviewer"
         ▼
       fixer ─► codex exec -m gpt-5.5 ...   ─► answer to the primary
```

Fixer has no agent loop, and it does not change a host. Each member uses
the sign-in, tools, and permissions of its own CLI. Fixer is one Python
file. It uses only the standard library.

## Terms

| Term | Meaning |
| --- | --- |
| Host | The CLI that you type into. |
| Primary | The model in the host. The primary calls the members. |
| Member | One role in the Team. A member has a runner and a model. |
| Runner | The CLI that runs a member. |

## Peers and specialists

| Kind | Memory |
| --- | --- |
| `peer` | A peer keeps one session with the primary. Each new call continues that session through the resume function of the CLI. The session stops when the Fixer server stops, normally at the end of the host session. |
| `specialist` | A specialist starts a new session for each call. |

The tool description tells the primary the kind of each member. Thus the
primary knows what it must send. Members do not consult other members.

## Supported CLIs

A CLI can be the host, a runner, or both. These results come from tests
with real models on 2026-10-04, and for Cursor on 2026-10-09.

| CLI | As host | Specialist | Peer | Read-only stops edits | Read-only stops shell commands |
| --- | --- | --- | --- | --- | --- |
| Claude Code (`claude`) | tested | tested | tested | yes | yes |
| Codex (`codex`) | tested | tested | tested | yes | yes |
| OpenCode (`opencode`) | tested | tested | tested | yes | **no** |
| fx (`fx`) | tested | tested | tested | yes | yes |
| Cline (`cline`) | not tested | tested | **not possible** | yes | **no** |
| Cursor (`cursor-agent`) | not tested | tested | tested | yes | see the note |

- Cline cannot continue a session without a terminal. Thus Cline can run
  only specialists.
- On OpenCode and Cline, a read-only member can run shell commands. Give
  these members only tasks where this is safe.
- The Cursor tests used the model `auto`. A read-only Cursor member refused
  to run `touch` in a shell. The test does not show if the tool or the
  model stopped the command.
- The fx tests used fx 0.0.12 with a Cline connection. The fx runner uses
  only standard fx flags.

## Install and configure

You need:

- Python 3.11 or later, on macOS or Linux.
- The CLI of each member, installed and signed in.

Do these steps:

1. Copy `team.example.toml` to `.fixer/team.toml` in your project. For
   one Team in all of your projects, put the file in a different place,
   for example `~/.config/fixer/team.toml`, and set `FIXER_TEAM` to its
   path.
2. Edit the Team file. The section [Team file](#team-file) gives the keys.
3. Check the file:

   ```sh
   python3 /path/to/fixer.py check
   ```

4. Add Fixer to your host. If you use `FIXER_TEAM`, give it to the server:
   add `-e FIXER_TEAM=/path/to/team.toml` to the Claude Code command, or
   `--env FIXER_TEAM=/path/to/team.toml` to the Codex command.

   | Host | Command or file |
   | --- | --- |
   | Claude Code | `claude mcp add fixer -- python3 /path/to/fixer.py serve` |
   | Codex | `codex mcp add fixer -- python3 /path/to/fixer.py serve` |
   | OpenCode | `opencode.json`: `{"mcp": {"fixer": {"type": "local", "command": ["python3", "/path/to/fixer.py", "serve"]}}}` |
   | fx | `.mcp.json`: `{"mcpServers": {"fixer": {"command": "python3", "args": ["/path/to/fixer.py", "serve"], "operation_timeout_ms": 900000}}}`. Then run `fx mcp trust approve fixer`. |

5. Start the host in the project directory. The members work there.
   Fixer reads the Team file from `--team`, then from `FIXER_TEAM`, then
   from `.fixer/team.toml` or `fixer.toml` in that directory.
6. Increase the time limit of the host for MCP tools. One member call can
   take some minutes.
   - Claude Code: set `MCP_TOOL_TIMEOUT=900000` (milliseconds).
   - Codex: in `~/.codex/config.toml`, under `[mcp_servers.fixer]`, set
     `tool_timeout_sec = 900`.
   - fx: set `operation_timeout_ms` in `.mcp.json`, as in step 4.
7. Approve the Fixer tools. A host that runs without a terminal cannot ask
   for approval, so approve the tools before you start it:
   - `claude -p`: add `--allowedTools mcp__fixer`.
   - `codex exec`: under `[mcp_servers.fixer]`, set
     `default_tools_approval_mode = "approve"`.

Then use your host as usual. The primary calls a member in three cases:

- The primary decides that the member can help.
- You tell the primary to call the member.
- A rule in your instructions file tells the primary to call the member.

## Team file

```toml
name = "engineering"
max_active = 4          # member runs at the same time
timeout_seconds = 900   # time limit for one call

[members.reviewer]
kind = "peer"
runner = "codex"
model = "gpt-5.5"
effort = "high"         # optional
description = "Independent reviewer. Give it the diff or the file names."
instructions = "Find correctness bugs. Give file:line for each bug."
read_only = true        # the default value
```

| Key | Required | Meaning |
| --- | --- | --- |
| `kind` | yes | `peer` or `specialist`. |
| `runner` | yes | `claude`, `codex`, `opencode`, `fx`, `cursor`, `cline`, or a name from `[commands]`. |
| `model` | yes | Fixer gives this value to the model flag of the runner. |
| `description` | yes | The primary sees this text. Tell the primary when to call this member. |
| `instructions` | no | The role of the member. Fixer sends it on the first call. |
| `read_only` | no | `true` is the default. `false` selects the write mode of the runner. |
| `timeout_seconds` | no | This value replaces the Team value for this member. |
| `effort` | no | The reasoning effort. Fixer gives it to the effort flag of the runner. Without it, the member uses the default of its CLI. |

Fixer keeps no list of effort values. The CLI is the authority:

- Codex and Cline refuse a value that they do not know. The call then
  fails with their message.
- Claude Code and OpenCode use their default effort for a value that they
  do not know, and give no error. Thus Fixer asks them first. It runs
  `claude --version` with and without `--effort`, and refuses the value if
  Claude Code adds a warning. A third run with a value that no CLI accepts
  must add output, or Fixer cannot check. This test only shows that Claude
  Code adds output for a value; it is not a full check of Claude Code. For
  OpenCode, the effort is a variant of the model: Fixer reads the variants
  of the model from `opencode models --verbose`.
- `fixer check` asks for each member. A running server asks at each call
  of a member, inside the time limit of the call. Thus a CLI that cannot
  answer stops only its member, and the call gives the reason.
- For Claude Code, Fixer also sets `CLAUDE_CODE_EFFORT_LEVEL`, because that
  variable has priority over `--effort`.

Fixer sends the effort that you request. The model, or settings of the CLI,
can still decrease it. fx has no effort setting in Fixer. Cursor puts the
effort in the model name, for example `claude-opus-5-5-xhigh`.

The tool name is the member id. An id has lowercase letters, digits, `-`,
and `_`. Fixer refuses unknown keys. Thus `fixer check` finds a typing
error before you start.

`[commands]` adds a different CLI for read-only specialists:

```toml
[commands]
my-cli = ["my-cli", "--model", "{model}", "--quiet"]
```

Fixer replaces `{model}`. Fixer sends the prompt on stdin, unless an
argument contains `{prompt}`. The command must print only the answer.

## Safety and limits

- `max_active` sets the maximum number of member runs at the same time,
  for each Team, across all processes.
- Each call has a time limit. If the host stops a call, or if the host
  itself stops, Fixer stops the process group of the member.
- Each member works in the directory of the server. Fixer sets the working
  directory and `PWD` to the same value, because OpenCode uses `PWD`.
- Fixer sets `FIXER_MEMBER` for each member. If the CLI of a member loads
  Fixer from your settings, that Fixer gives no tools.
- If a prompt is longer than 96 KiB, Fixer writes it to a temporary file.
  The member then reads the file.
- A member can read all of your workspace. This includes the Team file.
- `FIXER_LOG=/path` records each call as one JSON line: member, runner,
  model, effort, resume or new session, seconds, and exit status.

## Known problems

- The answer of a member can be wrong. In one test, a peer gave a wrong
  answer from its memory. The primary examined the answer and found the
  error. Fixer tells the primary to examine each answer.
- Free models can change without notice. During the tests, one Cline free
  model stopped. Also, the OpenCode free tier started to refuse other
  clients.
- Peer sessions stop when the Fixer server stops. A host that starts a new
  server for each request loses the sessions. Repeated `claude -p` calls
  are an example.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The unit tests examine the command lines of each adapter. They read real
CLI output from `tests/fixtures/`. They test the server with a stand-in
CLI.

`tests/test_live.py` runs real CLIs on real models. For each runner, it
tests a one-time call, a peer session against a specialist, and read-only
mode against write mode:

```sh
FIXER_LIVE=claude,codex FIXER_LIVE_CLAUDE=claude-haiku-4-5-20251001 FIXER_LIVE_CODEX=gpt-6-luna \
  python3 -m unittest tests.test_live -v
```

## Change Fixer

Obey these rules:

- Keep Fixer above the host. Use only MCP over stdio and the CLI of each
  member. Do not import, change, or fork a CLI.
- Put all details of one CLI in the adapter class of that CLI. The server
  must not know a CLI by name.
- Add a runner only with real tests. Run `tests/test_live.py` for the new
  runner. Save one real output in `tests/fixtures/` for its parser test.
- Use only the standard library.
- Refuse unknown keys in the Team file. Add a key only for a real need.

After a change, do these steps:

1. Run the unit tests. All tests must pass.
2. If you changed an adapter, run the live tests for that runner. The unit
   tests use saved output, so they cannot show that the real CLI accepts
   the flags.

The adapters use these flags. The versions are the versions that Fixer
was tested with.

| CLI | Version | One-time call | Session | Read-only | Effort |
| --- | --- | --- | --- | --- | --- |
| Claude Code | 2.1.295 | `-p --no-session-persistence` | `--session-id <uuid>`, then `--resume <uuid>` | default `-p` mode | `--effort <level>` |
| Codex | 0.162.0 | `exec --ephemeral` | id from `--json`, then `exec resume <id>` | `sandbox_mode="read-only"` | `-c model_reasoning_effort="<level>"` |
| OpenCode | 1.18.34 | `run` | id from `--format json`, then `--session <id>` | `--agent plan` | `--variant <name>` |
| fx | 0.0.12 | `ask --no-save` | id from `--json`, then `--resume-id <id>` | default mode | none |
| Cline | 3.0.64 | `--json "<prompt>"` | not possible without a terminal | `--plan` | `--thinking <level>` |
| Cursor | 2026.10.01 | `-p --output-format json` | `create-chat`, then `--resume <id>` | `--mode ask` | in the model name |

## Open items

1. Find a way for Cline peers. `cline --acp` keeps a live session. It is
   not tested.
2. Add an install command, so that users do not need a file path.

## History

Fixer was first a Zig extension. It compiled into a fork of fx. That
design was difficult to maintain, for three reasons:

- Upstream fx changed very quickly: 987 commits in the 26 days after the
  last sync.
- Fixer connected below the agent loop. Thus most upstream changes broke
  the fork.
- Each change needed 24 CI jobs on four platforms.

Commit `310ba91` is the last commit of the old design.

Licensed under [Apache-2.0](LICENSE).
