#!/usr/bin/env bash
set -euo pipefail

product_root="$(cd "$(dirname "$0")/.." && pwd)"
host_tests="$product_root/vendor/fx/tests/e2e"
shard_index="${1:?usage: test-host-e2e-shard.sh INDEX COUNT}"
shard_count="${2:?usage: test-host-e2e-shard.sh INDEX COUNT}"
bun_exe="${BUN:-bun}"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

export FX_E2E_DISABLE_DOTENV=1
export FX_ORCHESTRATION_E2E=1
export FX_REQUIRE_TMUX=1
cd "$host_tests"
"$bun_exe" ci-shards.ts --shard-count "$shard_count" --shard-index "$shard_index" > "$scratch/selection.txt"

shard_status=0
test_number=0
run_test() {
  local test_dir="$1" test_file="$2"
  local socket_dir="$scratch/tmux-$test_number"
  mkdir -p "$socket_dir"
  printf 'Running %s/%s\n' "$test_dir" "$test_file"
  if ! (cd "$test_dir" && TMUX_TMPDIR="$socket_dir" "$bun_exe" test --max-concurrency 1 "./$test_file"); then
    TMUX_TMPDIR="$socket_dir" tmux kill-server 2>/dev/null || true
    printf 'Retrying %s after resetting its tmux server\n' "$test_file"
    if ! (cd "$test_dir" && TMUX_TMPDIR="$socket_dir" "$bun_exe" test --max-concurrency 1 "./$test_file"); then
      shard_status=1
    fi
  fi
  TMUX_TMPDIR="$socket_dir" tmux kill-server 2>/dev/null || true
  test_number=$((test_number + 1))
}

while IFS= read -r test_file; do
  # Product tests are owned here; never run the host's historical copies.
  if [ -f "$product_root/tests/e2e/$test_file" ]; then
    continue
  fi
  run_test "$host_tests" "$test_file"
done < "$scratch/selection.txt"

if [ "$shard_index" = 0 ]; then
  # Schedule from the product manifest, independent of the host's file list.
  python3 - "$product_root/scripts/pgso/corpus.json" > "$scratch/product.txt" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1]))
for section in ("scenarios", "verification_scenarios"):
    for scenario in manifest[section]:
        if "test_file" in scenario:
            print(scenario["test_file"])
PY
  while IFS= read -r test_file; do
    run_test "$product_root/tests/e2e" "$test_file"
  done < "$scratch/product.txt"
fi
exit "$shard_status"
