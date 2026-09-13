# AGENTS.md

Fixer is a Zig orchestration extension assembled with the pinned fx support
fork in `vendor/fx`. Respect fx's existing contracts and runtime conventions.

## Design principle: respect the host

Fixer should extend fx while preserving the host's ownership boundaries,
execution paths, conventions, and guarantees. An fx maintainer should be
able to recognize the native design and understand where Fixer attaches to it.

Treat upstream's design as the starting point. Before implementing a feature,
read the closest native behavior and follow its call path. The pinned host
defines the interfaces available to Fixer today; upstream is the reference
when maintaining or extending that host.

Non-invasive integration is about the reach and consequences of a change,
not its line count. Prefer a few explicit contracts and clear ownership over
hidden coupling, indirect workarounds, or a second execution path. Additional
code is justified when it makes lifetimes, authority, or failure handling correct.

- Keep Team semantics and coordination policy in Fixer. Use fx's native
  execution, tools, permissions, persistence, and rendering mechanisms.
- Preserve the full guarantees of those mechanisms, including canonical
  user-input authority, permission checks, cancellation, resource ownership,
  session continuity, and useful error propagation.
- Reuse code only when its semantics fit. Sharing mutable state across
  independent runs is not safe reuse. Different lifecycles may justify
  separate adapters even when some code looks similar.
- When fx lacks a capability that Fixer actually needs, extend the appropriate
  host-owned service through a small typed contract. A necessary host fix is
  preferable to a product-side workaround that duplicates native behavior.
- Let concrete requirements justify abstractions. Avoid speculative plugin
  frameworks, broad refactors, and unrelated cleanup during feature work.
- Keep host changes cohesive and understandable on their own so upstream
  maintenance does not require reconstructing Fixer's product logic.

In change summaries, explain which module owns the behavior, which native
mechanism was reused, why any host change was necessary, and how the relevant
guarantees were verified. Explain the reasoning; a small diff alone is not
evidence of a good integration.

## Ownership

- The root Zig files and `domain/` own Team definitions, the Team editor,
  coordination, projections, and Fixer's protocol and presentation policy.
- `vendor/fx` owns the host contract, agent execution, providers, permissions,
  tools, persistence, and terminal rendering. Change the support fork in its
  own repository, then update this repository's submodule pin deliberately.
- Extension source may import only `std`, other Fixer source, and the named
  `fx_orchestration_host` module. Do not import private host implementation.
- The host owns the sole definition of the contract. Do not copy it here.
- The bundled `vendor/fx/fixer/` directory is a historical snapshot. This
  repository's build always selects `extension.zig` through custom mode.

## Development

Use the exact compiler in `.zigversion`. Initialize dependencies with
`git submodule update --init`. Run `zig fmt --check *.zig domain/`,
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
