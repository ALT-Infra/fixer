# Fixer

Fixer adds recursive multi-model Team orchestration to
[fx](https://github.com/vercel-labs/fx). This repository owns the Team editor,
coordination rules, specialist projections, and the protocol that returns
results to their callers.

The [fx support fork](https://github.com/ALT-Infra/fx) supplies the native
terminal UI, model transports, credentials, permissions, tools, sessions,
and background agent execution. It is pinned as the `vendor/fx` Git
submodule. Fixer imports the host's `fx_orchestration_host` contract; it does
not implement a second agent harness.

## Build and run

Use **Zig 0.16.0**, the exact version recorded in `.zigversion`.

```sh
git clone --recurse-submodules https://github.com/ALT-Infra/fixer.git
cd fixer
zig build -Doptimize=ReleaseSafe
./zig-out/bin/fx
```

For an existing clone, run `git submodule update --init` first. Builds work
offline once the pinned host and compiler are present. `zig build run`
also builds and launches the assembled application.

The build delegates to the pinned host with `-Dorchestration=custom` and
this repository's `extension.zig`. fx compiles the binary and installs
it in `vendor/fx/zig-out`; the wrapper installs that same binary at
`./zig-out/bin/fx`. The host's bundled Fixer source is a historical snapshot
and is not selected by this build. No installed copy on PATH is used.

The application still starts in native fx mode. Sign in and select a
provider through fx's native commands, then use `/fixer` to begin. User
settings, Team revisions, and sessions retain their existing `~/.fx/`
locations; this repository separation does not migrate runtime state.

## Teams and conversations

`/fixer` resumes the latest Fixer conversation or opens the Team library
when none exists. `/fixer teams` opens the library, `/fixer new` opens the
guided builder, and `/fixer off` returns to native fx.

The builder configures the Team name, provider, primary, peers, specialists,
per-role models and instructions, and specialist authority. Models come
from fx's live catalog. Teams contain a primary and at least one peer or
callable specialist, and each role uses a distinct catalog model.

Team revisions are immutable. Editing creates the next revision and starts
a new conversation. Existing conversations retain their exact Team revision,
including after a Team is removed from the library.

Each user turn starts with the configured primary. One peer holds leadership
and may answer, hand leadership to another peer, or coordinate work:

- Consultations return to their immediate caller and do not transfer leadership.
- Consultants can consult other peers and call their assigned specialists.
- Specialists receive bounded projections and selected attachments, with
  fx's tools and permission enforcement.
- Specialist dependencies, consultation depth, and ancestry checks bound work.
- Tool activity and operational notices stream through fx. Fixer validates
  terminal machine envelopes and explicitly publishes the human answer.

Native fx subagents and native Codex/Grok modes remain unavailable inside
Fixer mode. `/fixer off` restores the native environment.

## Verify

Bun and tmux are required for deterministic TUI tests; no real model
credentials are needed.

```sh
python3 scripts/check-layout.py
zig fmt --check *.zig domain/
zig build test -Doptimize=ReleaseSafe
zig build test-e2e -Doptimize=ReleaseSafe
```

`zig build crucible-host -Doptimize=ReleaseSafe` combines the focused unit
and TUI checks. `zig build test-host -Doptimize=ReleaseSafe` runs the full
host unit suite with this extension and is normally left to Full CI.

Full CI checks the assembled product on Linux x86_64 and aarch64 and macOS
x86_64 and aarch64. It preserves the host's four deterministic E2E shards
per platform, replaces the historical Fixer scenarios with this repository's
scenarios, and excludes credentialed live tests.

See [CONTRIBUTING.md](CONTRIBUTING.md) for dependency updates and the
verification requirements. [PROVENANCE.md](PROVENANCE.md) records the
extraction baseline. Licensed under [Apache-2.0](LICENSE).
