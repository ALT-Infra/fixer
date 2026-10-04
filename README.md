# Fixer

Fixer gives the coding agent you already use a Team of models from other
providers.

You write a Team file. Each member has a CLI, a model, and a role. Fixer is
an MCP server: your agent sees one tool per member. A call runs that member
through its own CLI, on its own model, in your workspace, and returns its
answer as the tool result.

```
you ─► your agent (the primary, for example Claude Code)
         │ calls the tool "reviewer"
         ▼
       fixer ─► codex exec -m gpt-5.5 ...   ─► answer back to the primary
```

Fixer has no agent loop and patches no host. Each member uses its CLI's
own sign-in, tools, and permissions. Fixer is one file of standard-library
Python.

## Two kinds of member

| Kind | Memory |
| --- | --- |
| `peer` | Keeps one session with the primary. Each later call continues that session through the CLI's own resume. The session lasts while the Fixer server runs, which is normally the host session. |
| `specialist` | Starts fresh on every call. |

The tool description tells the primary which kind each member is, so it
knows what to send. Members do not consult each other.

## Support

A CLI can be the **host** (where the primary runs) or a **member runner**
(where Fixer runs a member). Results below come from real runs on
2026-10-04.

| CLI | As host | Specialist | Peer | Read-only blocks edits | Read-only blocks shell |
| --- | --- | --- | --- | --- | --- |
| Claude Code (`claude`) | tested | tested | tested | yes | yes |
| Codex (`codex`) | tested | tested | tested | yes | yes |
| OpenCode (`opencode`) | tested | tested | tested | yes | **no** |
| fx (`fx`) | tested | tested | tested | yes | yes |
| Cline (`cline`) | not tested | tested | **not possible** | yes | **no** |
| Cursor (`cursor-agent`) | not tested | not tested | not tested | — | — |

- Cline cannot resume a session without a terminal, so it runs
  specialists only.
- On OpenCode and Cline, a read-only member can still run shell commands.
  Give those members work where that is acceptable.
- Cursor support follows its help text. It has not run with a real model.

## Start

You need Python 3.11 or later on macOS or Linux, and each member's CLI,
installed and signed in.

1. Copy `team.example.toml` to `.fixer/team.toml` in your project. Edit it.
   Then check it:

   ```sh
   python3 /path/to/fixer.py check
   ```

2. Register Fixer in your host. Run the host from the project directory,
   because Fixer finds `.fixer/team.toml` there and members work there.

   | Host | Command or file |
   | --- | --- |
   | Claude Code | `claude mcp add fixer -- python3 /path/to/fixer.py serve` |
   | Codex | `codex mcp add fixer -- python3 /path/to/fixer.py serve` |
   | OpenCode | `opencode.json`: `{"mcp": {"fixer": {"type": "local", "command": ["python3", "/path/to/fixer.py", "serve"]}}}` |
   | fx | `.mcp.json`: `{"mcpServers": {"fixer": {"command": "python3", "args": ["/path/to/fixer.py", "serve"], "operation_timeout_ms": 900000}}}`, then `fx mcp trust approve fixer` |

3. Allow enough time. A member call can take minutes.
   - Claude Code: set `MCP_TOOL_TIMEOUT=900000` (milliseconds).
   - Codex: in `~/.codex/config.toml`, under `[mcp_servers.fixer]`, set
     `tool_timeout_sec = 900`.
   - fx: `operation_timeout_ms` in `.mcp.json`, as above.

4. Approve Fixer's tools if your host asks. A headless host (for example
   `claude -p`) cannot ask; allow the tools in advance, for example
   `claude -p --allowedTools mcp__fixer`.

Then work as usual. The primary calls members when it decides to, when
you ask it to, or when a rule in your instructions file tells it to.

## Team file

```toml
name = "engineering"
max_active = 4          # member runs at the same time
timeout_seconds = 900   # for one call

[members.reviewer]
kind = "peer"
runner = "codex"
model = "gpt-5.5"
description = "Independent reviewer. Pass the diff or name the files."
instructions = "Find correctness bugs. Cite file:line."
read_only = true        # the default
```

| Key | Required | Meaning |
| --- | --- | --- |
| `kind` | yes | `peer` or `specialist`. |
| `runner` | yes | `claude`, `codex`, `opencode`, `fx`, `cursor`, `cline`, or a name from `[commands]`. |
| `model` | yes | Passed to the runner's model flag. |
| `description` | yes | Shown to the primary. Say when to call this member. |
| `instructions` | no | The member's role, sent on the first call. |
| `read_only` | no | `true` by default. `false` uses the runner's write mode. |
| `timeout_seconds` | no | Overrides the Team value. |

The tool name is the member id. Ids use lowercase letters, digits, `-`
and `_`. Fixer rejects unknown keys, so a typo fails at `fixer check`.

`[commands]` adds another CLI for read-only specialists:

```toml
[commands]
my-cli = ["my-cli", "--model", "{model}", "--quiet"]
```

`{model}` is replaced. The prompt goes to stdin unless an argument contains
`{prompt}`. The command must print only the answer.

## Safety and limits

- `max_active` counts live member runs for each Team, across processes.
- Each call has a time limit. When the host cancels a call or exits, Fixer
  stops the member's whole process group.
- Each member runs in the server's directory. Fixer sets both the working
  directory and `PWD`: OpenCode follows `PWD`.
- Fixer sets `FIXER_MEMBER` in each member's environment. If a member's CLI
  loads Fixer from your settings, that Fixer offers no tools.
- A prompt longer than 96 KiB goes to a temporary file that the member reads.
- A member can read your workspace, the Team file included.
- A member's answer is a claim. The primary is told to check it, but the
  primary decides.
- `FIXER_LOG=/path` records each call as one JSON line: member, runner,
  model, resumed or not, seconds, exit status.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The unit tests check each adapter's command lines, parse real CLI output
saved in `tests/fixtures/`, and check the server with a stand-in CLI.

`tests/test_live.py` runs real CLIs on real models. For each runner it
checks a one-time call, a peer session against a specialist, and
read-only against write mode:

```sh
FIXER_LIVE=claude,codex FIXER_LIVE_CLAUDE=claude-haiku-4-5-20251001 FIXER_LIVE_CODEX=gpt-6-luna \
  python3 -m unittest tests.test_live -v
```

## History

Fixer started as a Zig extension compiled into a fork of fx. That version
is on the `main` branch. [docs/ANALYSIS.md](docs/ANALYSIS.md) records why
it changed and what was tested.

Licensed under [Apache-2.0](LICENSE).
