# AGENTS.md

Fixer is a Zig orchestration extension assembled with the pinned fx support
fork in `vendor/fx`. Respect fx's existing contracts and runtime conventions.

## Ownership

- `src/` owns Team definitions, the Team editor, coordination, projections,
  and Fixer's protocol and presentation policy.
- `vendor/fx` owns the host contract, agent execution, providers, permissions,
  tools, persistence, and terminal rendering. Change the support fork in its
  own repository, then update this repository's submodule pin deliberately.
- Extension source may import only `std`, other Fixer source, and the named
  `fx_orchestration_host` module. Do not import private host implementation.
- The host owns the sole definition of the contract. Do not copy it here.
- The bundled `vendor/fx/fixer/` directory is a historical snapshot. This
  repository's build always selects `src/extension.zig` through custom mode.

## Development

Use the exact compiler in `.zigversion`. Initialize dependencies with
`git submodule update --init`. Run `zig fmt --check build.zig src/`,
`zig build test -Doptimize=ReleaseSafe`, and
`zig build test-e2e -Doptimize=ReleaseSafe` for focused verification.
The full host unit and deterministic E2E suites belong in Full CI.

Follow fx's allocator, `errdefer`, error propagation, explicit I/O, and minimal
public surface conventions. Never bypass host permissions or reimplement
host execution inside Fixer. Keep product behavior out of the build wrapper.
Do not add runtime dependencies beyond Zig's standard library without discussion.
Do not commit build output, credentials, recordings, or user runtime state.

Keep Fixer unit tests beside their code. Every root `tests/e2e/*.test.ts` must
have exactly one classification in `scripts/pgso/corpus.json`. Preserve
deterministic fixtures and the explicit opt-in for credentialed live tests.
Update README and CONTRIBUTING when behavior or build steps change.

## Verification and PRs

Always exercise the freshly built `./zig-out/bin/fx` from this checkout,
never `fx` from PATH or an installed copy. Drive a real interaction and
check exit status, stderr, and visible behavior; unit tests alone are
insufficient for terminal and thread lifetime changes.

After focused local checks pass, create a checkpoint commit, push a feature
branch, and open a draft PR. Use exactly one `type:` label; extraction and
build changes are `type: maintenance`. Do not create version tags manually.

Do not declare a change ready or mark its PR ready until Full CI passes on
the exact commit on Linux x86_64 and aarch64 and macOS x86_64 and aarch64,
the local binary interaction passes, and `scripts/ship-gate.sh` reports SHIP.
If verification is blocked, report the missing evidence explicitly.
