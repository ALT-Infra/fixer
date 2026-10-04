# Fixer and fx: analysis and decision record

Date: 2026-10-04. Scope: `ALT-Infra/fixer`, `ALT-Infra/fx`, and upstream
`vercel-labs/fx`. Style: close to ASD-STE100. Technical names stay as they
are in the code.

## 1. Summary

You could not keep up because Fixer was built inside a fork of a very fast
upstream. Fixer also connected below the agent loop, not above it. Each
upstream change near sessions, the run loop, the footer UI, or providers
broke the fork. The process added more cost to each change.

Upstream fx now has most of what Fixer built: named persistent subagents,
a model and instructions for each child, and configurable providers. Two
parts of the Fixer idea are still not in upstream:

- A Team that you define one time and use in every session.
- Members that consult other members.

Decision: Fixer is now a small MCP server and a Team file. It does not
need a fork. It works with any host that supports MCP. The fx fork
becomes upstream plus one small patch that upstream can accept. When
upstream accepts it, delete the fork.

## 2. Method

1. I read all source, tests, CI, and documents in both repositories.
2. I measured the fork against upstream with `git`.
3. I fetched upstream `main` (2026-10-03) and compared it with the fork's
   last sync (`43c11dc`, 2026-09-07).
4. I built the old Fixer with its pinned host and Zig 0.16.0. I ran its
   unit tests and its deterministic TUI tests.
5. I signed in to Cline with your approval. I ran real models through the
   fork, through the new Fixer, and through patched upstream fx.

## 3. Findings

### 3.1 Upstream speed

- Upstream started on 2026-08-11. It had 1,755 commits by the sync point
  on 2026-09-07. That is approximately 65 commits each day.
- At the sync point, upstream had 661,207 lines of Zig.
- After the sync, upstream added 987 commits in 26 days. They changed 579
  files: +151,779 and −37,937 lines.
- The changes after the sync include a new session layer ("sessions v2").
  The fork's orchestration code sits directly on the old session layer.

One person cannot rebase a deep fork onto this rate of change.

### 3.2 Size and reach of the fork

The fork changed 146 files: +25,760 and −518 lines. The changes have
three parts:

| Part | Lines | Where |
| --- | --- | --- |
| Fixer itself | 6,735 | `fixer/` (bundled copy) |
| Host support for Fixer | 5,949 | `src/core/orchestration/`, isolated runs, footer UI |
| Providers and search | 4,583 | OpenCode, Cline, Parallel, models.dev |

The rest is changes in `main.zig` (+741), auth, the slash menu, help
text, and tests. `AGENTS.md` says not to put feature logic in `main.zig`.

### 3.3 Signs of the sync cost

- 31 of your 55 different commit messages occur two times in history. You
  rebased the work, and then you merged it back ("catch up from 250 to 12
  behind upstream").
- Several commits only repair upstream test expectations after a merge.
  Examples: "Expect 36 slash menu entries", "Fix 4 CI goldens".
- The host contract reached `api_version` 13 in three weeks.

### 3.4 The integration layer

Fixer connected below the agent loop. Each agent ended its run with a
strict JSON object: `answer`, `handoff`, or `coordinate`. Fixer parsed the
object and started new runs. A tool call gives the same result inside one
run. Because Fixer did not use tool calls, the host needed these parts:

- Custody of the user turn across separate runs.
- Transfer of conversation history from one run to the next run.
- A setting to hide the model's text (`render_assistant_text = false`),
  and a separate path to show the answer (`publish_answer`).
- Retries when a model wrote an incorrect JSON object.
- A run manager and an isolated run path, apart from native subagents.

Thus Fixer built a second subagent system. Its own `AGENTS.md` and
`README` say "do not implement a second agent harness". The README also
says that native subagents are not available in Fixer mode.

The "host contract" is not general. Its types name Fixer's roles:
`leader`, `peer`, `specialist`, `collaboration_id`, `delegation_id`.

### 3.5 The two-repository split

The split did not make the parts independent:

- Fixer compiles only into a custom build of the fork.
- The fork contains a frozen copy of Fixer, and its tests use that copy.
- A new Fixer feature often needs a fork commit, a submodule update, and
  CI in both repositories.

### 3.6 Process cost

Each push to a branch started 24 CI jobs: four platforms, with one native
job and four E2E shards on each, plus four gate jobs. Each native and E2E
job built the full host. A change was "ready" only after all 24 jobs passed on the exact
commit and `ship-gate.sh` said SHIP. Each E2E file also needed a class in
upstream's PGSO corpus. That corpus serves upstream's binary optimization.
It does not serve Fixer.

These rules came from upstream, where a company team and AI agents make
about 65 commits each day. For one person, the rules make each change slow.

### 3.7 Provider changes outside your control

I tested the free access that the fork added:

- OpenCode Zen free models now refuse other clients: "OpenCode's free tier
  can only be used from within OpenCode".
- Cline free models refuse a request without an `X-CLIENT-TYPE` header.
  With the header that the fork sends (`fx`), all four free models answer.
- Cline account tokens expire after one hour. A refresh needs a second
  call to register the new token.

Thus the provider code needs repairs that you cannot plan.

### 3.8 Slop

These items cost effort and give little or no value:

- **Event sourcing with no store.** `domain/projection.zig` folds a
  "durable event stream" with sequence numbers. Nothing writes the events
  to disk. The fold is only an in-memory state check.
- **Checks that cannot fail.** `decision.zig` checks a Team pin that the
  runtime itself just wrote.
- **Rules that block valid use.** A Team must use a different model for
  each role. A Team with only a primary is refused. Only three providers
  are allowed.
- **Strict result envelopes.** Specialists must return
  `{"result", "findings", "risks", "confidence"}`. A model's "confidence"
  number has no meaning, and the format causes retries.
- **Leadership handoff.** It adds state and rules. The lead can relay or
  quote a member's answer, and the user can change the model with `/model`.
- **Team revisions with digests and a TUI editor.** A text file in the
  repository, under `git`, gives revisions and review with no code.
- **Unrelated scope.** A GUI runtime study and a web search backend
  (Parallel) are in the fork. They do not serve Team orchestration.
- **Process prose.** The `AGENTS.md` files state principles that the code
  does not follow (see 3.4).
- **Repeated test scaffolding.** Each runtime test defines its own capture
  type with fixed buffers of 50 to 80 lines.

### 3.9 What works today

| Item | Result |
| --- | --- |
| Old Fixer: build and focused unit tests (ReleaseSafe) | Pass, 322 s |
| Old Fixer: deterministic TUI tests | 10 of 10 pass, 39 s |
| Fork `fx ask` with Cline free models | 4 of 4 models answer |
| Upstream `fx` with Cline, no patch | Cannot work: no way to send `X-CLIENT-TYPE` |

The old tests use a fake provider that returns the expected JSON. Thus
they prove the state machine. They do not prove that a Team of real models
helps, or that a real model obeys the JSON protocol.

## 4. Why you could not keep up

The causes, from most to least important:

1. You forked a host that changes at about 65 commits each day.
2. Fixer connected below the agent loop. Thus it touched the parts of the
   host that change most.
3. The JSON envelope protocol caused most of the host changes (3.4).
4. The split into two repositories doubled the work, but did not make the
   parts independent.
5. The CI and "ready" rules made each change cost hours.
6. Provider work in the fork added external breakage.

## 5. Questions about the approach

| Premise | Judgement |
| --- | --- |
| "Fixer needs its own copy of the agent." | No. MCP and agent CLIs are stable, public surfaces. Use them. |
| "Coordination needs a strict protocol." | No. A tool call and its text result are enough. The caller is a model. |
| "Each role needs a different model." | No. A different model is often useful. A rule that forces it is not. |
| "Peers need leadership handoff." | No. The lead keeps the session and relays answers. |
| "Recursion is the core feature." | Keep it, with a hard limit. Most value comes from one level. Default `max_depth = 2`. |
| "A Team of models gives better results." | Sometimes. A different model as a reviewer can find errors. It can also add false errors (see 7). The lead must check member claims. |
| "Zig is the right language for this part." | No. The part is glue code. Zig changes its standard library in each release; 0.17.0 is out and the code pins 0.16.0 exactly. |

## 6. Decision for the next phase

Note: section 10 replaces 6.1, 6.3, and the nesting parts of 8. Fixer no
longer has nested consultation, `consults`, or `max_depth`.

### 6.1 What Fixer is now

Fixer is one file, `fixer.py`. It has approximately 550 lines and uses
only the Python standard library.

1. You write `.fixer/team.toml`. Each member has a model, a description,
   a role, and an optional list of members that it may consult.
2. The host starts `fixer serve` as an MCP server.
3. The lead sees one tool, `ask_<member>`, for each member it may call.
4. A call starts the member as a headless agent process on its own model.
   The default runner is `fx ask --no-save --model <model>`.
5. The member's process can start its own `fixer serve`. It then sees the
   tools of the members that it may consult.
6. The final answer of the member becomes the tool result.

These limits control the call tree:

- `FIXER_CHAIN` carries the chain to each nested server. No member sees a
  tool for itself or for a member above it. At `max_depth`, no tools show.
- `max_active` counts live member processes for each Team in a file
  directory. It stops a call tree if a host drops `FIXER_CHAIN`.
- Each call has a time limit. Cancellation or host exit stops the whole
  member process group.
- Members are read-only unless `writes = true`. The host's permission
  system still decides each action.

### 6.2 What I removed from the Fixer branch

- The Zig extension: runtime, Team editor, domain files (6,735 lines).
- The `vendor/fx` submodule and the build wrapper.
- The 24-job CI, the ship gate, the shard script, and the PGSO manifest.
- Handoff, envelopes, revisions, digests, and the forced distinct models.

The old code stays on `main` and in history.

### 6.3 What I kept

- The Team idea: fixed roles, each with its own model and instructions.
- Directed authority: each member lists the members it may call.
- Nested consultation, with depth limits and cycle prevention.
- Read-only members by default.
- The license and the name.

### 6.4 The fx fork

The fork's Fixer support is not necessary now. Its only function that you
still need is Cline access. A small upstream change gives that access:

- The fx branch now has the upstream tree, plus one commit. The commit
  adds a `headers` field to configured connections (91 added lines, with tests).
- Fork history stays in place. The branch moves forward with no force push.

Next step for fx: offer the `headers` commit to `vercel-labs/fx` as a
pull request. If upstream accepts it, delete the fork. If upstream refuses
it, keep only this one commit and rebase it. A one-commit rebase is small.

### 6.5 Rules to keep it maintainable

1. Do not fork a host. Use MCP and CLI flags only.
2. Keep CLI details in runner data, not in logic.
3. Keep `fixer.py` small. Add a feature only after a real run shows a need.
4. Test with real models before you trust a change. Use unit tests for the
   protocol and limits only.
5. Keep CI to one small job matrix.

## 7. Verification record

All runs used Cline free models through your account.

| Run | Path | Result |
| --- | --- | --- |
| Unit tests | `python3 -m unittest discover -s tests` | 23 pass |
| fx connects to Fixer | fork fx, project `.mcp.json` | 2 tools found, protocol 2025-11-25 |
| Live 1, first try | lead mimo-v2.6-flash → reviewer | fx refused the call: `review_unavailable`. Headless fx cannot ask for approval. |
| Live 1, tools allowed | lead mimo → reviewer deepseek-v4.1-flash | Pass, 151 s. Both planted bugs found. |
| Live 2, nested | lead mimo → reviewer deepseek (60.6 s) → scout space-bunny-alpha (20.9 s) | Pass. Chain `reviewer,scout` in the log. Both bugs found. |
| Live 2, quality | same | The reviewer reported a `TabError` that does not exist. The lead repeated it. |
| Upstream fx 0.0.12 + `headers` patch | `fx ask` on two Cline free models | Pass. The same request without `headers` gets HTTP 403. |
| Live 3, upstream host (`tests/test_live.py`) | lead mimo → reviewer deepseek (57.3 s) → scout space-bunny-alpha (40.1 s) | Pass, 98 s. Both bugs found. The lead checked the reviewer's claims before it reported them. |

The live tests found two problems that the fake tests could not find:

- A headless host refuses MCP tools that are not allowed in advance. The
  README now gives the setting.
- A member can give a false claim, and the lead can repeat it. Fixer now
  tells the lead that a member's answer is a claim to check.

Live 3 ran on stock upstream fx with only the `headers` patch. Thus Fixer
needs no Fixer-specific host code.

## 8. Where to start

1. Read `README.md`. Make `.fixer/team.toml` in one real project.
2. Use the Team for one week of real work. Record each consultation with
   `FIXER_LOG`.
3. After the week, read the log. Remove members that did not help.
4. Offer the fx `headers` commit upstream.
5. Do these only if real use shows a need:
   - Persistent members that keep context between calls, with each CLI's
     resume flag.
   - Runners for other CLIs, after you test each one.
   - A direct API runner for advisors that need no tools. It is faster than
     a full agent process.

## 9. Risks and limits

- Each consultation is a full agent run. It costs time and tokens.
- Each runner depends on a CLI's flags. A flag change breaks only that
  runner, and the fix is in data.
- A host can drop environment variables for MCP servers. Then
  `max_active` is the only limit on depth.
- Cline's free access depends on Cline's policy. It changed during this
  project, and it can change again.

## 10. Phase 2: the product (2026-10-04)

### 10.1 Decisions

1. **Two surfaces.** A CLI can be the host, where the primary runs. A CLI
   can also be a runner, where Fixer runs a member. A host needs only MCP
   and setup steps. A runner needs an adapter and a real test.
2. **Many providers in one Team.** Each member names its own CLI. Thus one
   Team can use Anthropic, OpenAI, OpenCode, and Cline models together. The
   old Fixer used one provider for each Team.
3. **Two kinds of member.**
   - A peer keeps one session with the primary. The member's CLI keeps the
     session; Fixer keeps only the session id.
   - A specialist starts fresh on every call.
4. **The primary knows the kind.** The tool description says which kind a
   member is. Thus the primary knows what it must send.
5. **No nested consultation.** Members do not consult each other. If a
   member's CLI loads Fixer, that Fixer offers no tools.
6. **Read-only is explicit.** `read_only` is in the Team file. It is `true`
   by default. Fixer does not infer it from a description.
7. **One adapter for each CLI.** Each adapter holds that CLI's flags and
   output format. The server does not know any CLI by name.

### 10.2 What the CLIs support

I read each CLI's current help text. Then I ran each CLI with real models,
except Cursor.

| CLI | Version | One-time call | Session | Read-only flag |
| --- | --- | --- | --- | --- |
| Claude Code | 2.1.289 | `-p --no-session-persistence` | `--session-id <uuid>`, then `--resume <uuid>` | default `-p` mode |
| Codex | 0.160.0 | `exec --ephemeral` | id from `--json`, then `exec resume <id>` | `sandbox_mode="read-only"` |
| OpenCode | 1.18.34 | `run` | id from `--format json`, then `--session <id>` | `--agent plan` |
| fx | 0.0.12 | `ask --no-save` | id from `--json`, then `--resume-id <id>` | default mode |
| Cline | 3.0.68 | `--json "<prompt>"` | not possible without a terminal | `--plan` |
| Cursor | 2026.10.01 | `-p --output-format json` | `create-chat`, then `--resume <id>` | `--mode ask` |

### 10.3 Verification record

All runs used real models. Codex used your ChatGPT sign-in. Cline used your
Cline sign-in. OpenCode used its free models with no sign-in.

| Test | Result |
| --- | --- |
| Unit tests (parsers on saved real output, server on a stand-in CLI) | 31 pass |
| Live, Claude Code runner | one-time, peer session, read-only, write: pass |
| Live, Codex runner | one-time, peer session, read-only, write: pass |
| Live, OpenCode runner | one-time, peer session, read-only, write: pass |
| Live, fx runner (upstream fx with the `headers` patch, Cline model) | one-time, peer session, read-only, write: pass |
| Live, Cline runner | one-time, read-only, write: pass. Peers: not possible. |
| Host Claude Code; members on Codex (peer), OpenCode, Cline | Pass, 80 s. The resumed peer call took 4.9 s. |
| Host Codex; members on OpenCode and Claude Code | Pass, 31 s |
| Host OpenCode (free model); member on OpenCode | Pass, 20 s |
| Cursor, as host or runner | Not tested: no Cursor account |

### 10.4 Problems that only real runs found

1. **Wrong directory.** OpenCode follows `PWD`, not the real working
   directory. A member wrote a file into another project. Fixer now sets
   both for each member.
2. **Read-only is weaker on two CLIs.** OpenCode's plan agent and Cline's
   plan mode block edit tools, but shell commands still run. A Cline member
   ran Python and wrote `__pycache__`. On OpenCode's free tier, a config that
   denies shell commands makes OpenCode refuse the request. On Cline, with
   auto-approve off, reads fail too. Thus Fixer cannot close this gap.
3. **Cline cannot resume headless.** `--id` always opens interactive mode.
4. **Codex refuses unapproved MCP tools in `exec`.** The fix is
   `default_tools_approval_mode="approve"` for that server.
5. **Free models change without notice.** Cline's DeepSeek promotion ended
   during the tests. OpenCode's free tier now works only from OpenCode.
6. **A failed member could hide its exit status** when its output was not
   readable. Fixer now reports the exit status first.
7. **A member can read the Team file.** A fresh Codex member found a
   test string in `.fixer/team.toml`.
8. **A peer can answer wrongly from memory.** In the host test, the Codex
   peer gave a wrong follow-up answer. The primary checked it and found the
   error.

### 10.5 Open items

1. Test Cursor with a real account. Expect faults only in its adapter: a
   flag, the JSON field names, or headless resume.
2. Cline peers: try `cline --acp`, which keeps a live session.
3. Peer sessions end when the Fixer server stops. A host that starts a new
   server for each turn (for example repeated `claude -p`) loses them.
4. An install command, so that users do not need a file path.
5. Offer the fx `headers` commit to vercel-labs/fx.
