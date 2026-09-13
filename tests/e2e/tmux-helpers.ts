import { resolve } from "node:path";
import {
  TmuxSession as HostTmuxSession,
  tmuxAvailable,
} from "../../vendor/fx/tests/e2e/tmux-helpers";

// Reuse the host's terminal harness, but always drive this checkout's binary.
const FX_BIN = resolve(import.meta.dirname, "../../zig-out/bin/fx");
const FX_COMMAND = `'${FX_BIN.replaceAll("'", "'\\''")}'`;
if (process.env.FX_REQUIRE_TMUX === "1" && !tmuxAvailable()) {
  throw new Error("Fixer TUI verification requires tmux");
}

export { tmuxAvailable };
export type TmuxSession = HostTmuxSession;
export const TmuxSession = {
  create(options: Parameters<typeof HostTmuxSession.create>[0] = {}) {
    return HostTmuxSession.create({ ...options, cmd: FX_COMMAND });
  },
};
