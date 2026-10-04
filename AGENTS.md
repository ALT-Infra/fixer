# AGENTS.md

Fixer is one file, `fixer.py`: an MCP server in standard-library Python
3.11+. Read `README.md` for what it does and `docs/ANALYSIS.md` for why it
has this form.

## Rules

- Keep Fixer above the host. Use only public surfaces: MCP over stdio, and
  each member's CLI run as a process. Do not import, patch, or fork a CLI.
- Put everything that depends on one CLI's flags or output format in that
  CLI's adapter class. The server must not know any CLI by name.
- Add a runner only with a real test: run `tests/test_live.py` for it, and
  save a real output in `tests/fixtures/` for its parser test.
- No dependencies outside the standard library.
- Reject unknown Team file keys. Do not add a key without a use for it.
- Members do not consult each other.

## Verify

1. Run `python3 -m unittest discover -s tests -v`. It must pass.
2. For a change to an adapter, also run the live test for that runner.
   Unit tests use saved output and a stand-in CLI, so they cannot show that
   the real CLI still accepts the flags.
3. Report what you ran and what you did not run.
