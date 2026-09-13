# Contributing to Fixer

Fixer depends on the fx support fork in one direction. The Git submodule
entry records the exact host commit; `.zigversion` records the compiler.
Repository names stay stable when either revision changes.

## Ownership

| Change | Owner |
| --- | --- |
| Teams, editor, coordination, projections, outcome validation | Fixer `src/` |
| Agent runs, permissions, tools, providers, sessions, rendering | fx support fork |
| Typed host API and lifecycle guarantees | fx `src/core/orchestration/` |
| Product scenarios and assembled product verification | Fixer `tests/` and CI |
| Generic terminal fixtures and native regression tests | fx `tests/` |

Extension source imports only `std`, other extension files, and the named
`fx_orchestration_host` module. The host owns the contract; do not duplicate
its types or reach into its implementation from extension code.

The wrapper delegates compilation and host test collection to fx. Keep it
focused on assembly. If fx needs a new capability, implement that capability
in the support fork and expose a typed contract before using it here.

The `vendor/fx/fixer/` directory belongs to the historical pinned checkout.
New Fixer development happens only in this repository's `src/`. Keeping the
snapshot allows the support baseline to retain its original tests without
making the support fork depend on a moving Fixer repository.

## Local work

```sh
git submodule update --init
python3 scripts/check-layout.py
zig fmt build.zig src/
zig build test -Doptimize=ReleaseSafe
zig build test-e2e -Doptimize=ReleaseSafe
```

Use Zig 0.16.0. `-Dtarget` and `-Dcpu` are forwarded to fx. `-Dbun` selects
a Bun executable for TUI tests. Runtime verification always uses the
freshly assembled `./zig-out/bin/fx`, never a binary from PATH.

The E2E harness uses private temporary homes, local provider fixtures,
real TTYs, stderr capture, and exit-status checks. Its small adapter selects
the product binary while reusing fx's tmux helper. The live suite is kept
under `tests/e2e/tui-orchestration-live.test.ts` and requires explicit
`FX_ORCHESTRATION_LIVE=1` plus real credentials; it is not a deterministic gate.

Every root product E2E file must be classified once in
`scripts/pgso/corpus.json`. This is the product's classification manifest,
not a replacement for the host's complete PGSO training corpus. Full CI
validates both ownership lists and schedules deterministic product scenarios
on shard zero, independently of the host's historical filenames.

## Updating the host

Make and verify support changes in the separate fx checkout. Publish the
support commit before advancing this repository's pin:

```sh
git -C vendor/fx fetch origin
git -C vendor/fx checkout --detach <full-fx-commit>
git add vendor/fx
python3 scripts/check-layout.py
zig build test -Doptimize=ReleaseSafe
zig build test-e2e -Doptimize=ReleaseSafe
```

Commit the new pin with any corresponding extension changes. Run Full CI
on that exact product commit. A contract API number alone is not a
compatibility guarantee: the host revision, compiler, and assembled tests
are the compatibility evidence. The pin does not update automatically when
the support fork or upstream advances.

## Review and verification

After focused checks and a real binary interaction pass, push a checkpoint
commit on a feature branch and open a draft PR. Use one `type:` label;
build and extraction work use `type: maintenance`.

Full CI runs the native unit checks and all four isolated deterministic E2E
shards on each supported Linux and macOS architecture. A prior run, a partial
matrix, or a skipped job does not qualify a new commit. `scripts/ship-gate.sh`
checks a clean checkout and all four Full suite jobs for the exact current
commit. It does not substitute for personally exercising the local binary.

Do not mark a PR ready until those checks pass. Do not run live model tests
or publish releases as an incidental part of verification.

## Existing clones after the separation

The old fork repository is now `ALT-Infra/fx`. Existing clones of that fork
should point their fork remote there, for example:

```sh
git remote set-url fork https://github.com/ALT-Infra/fx.git
```

Keep the upstream remote pointing at `vercel-labs/fx`. Clone the new Fixer
repository separately; it has extracted extension history and is not a
continuation of the full fork branch. Existing user profiles and saved
conversations need no migration.
