#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
test -z "$(git status --porcelain)" || { printf 'HOLD: working tree is not clean\n' >&2; exit 1; }
revision="$(git rev-parse HEAD)"
repository="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
run_id="$(gh run list --repo "$repository" --workflow full-ci.yml --commit "$revision" --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
test -n "$run_id" || { printf 'HOLD: no Full CI run for %s\n' "$revision" >&2; exit 1; }
result="$(gh api "repos/$repository/actions/runs/$run_id" --jq '[.head_sha, .status, .conclusion] | @tsv')"
test "$result" = "$(printf '%s\tcompleted\tsuccess' "$revision")" || {
  printf 'HOLD: Full CI has not succeeded for %s\n' "$revision" >&2; exit 1;
}

jobs_file="$(mktemp)"
trap 'rm -f "$jobs_file"' EXIT
gh api "repos/$repository/actions/runs/$run_id/jobs?per_page=100" > "$jobs_file"
python3 - "$jobs_file" <<'PY'
import json, sys
expected = {f"Full suite ({p})" for p in (
    "linux-x86_64", "linux-aarch64", "macos-x86_64", "macos-aarch64"
)}
jobs = [job for job in json.load(open(sys.argv[1]))["jobs"] if job["name"] in expected]
if len(jobs) != 4 or {job["name"] for job in jobs} != expected or any(job["conclusion"] != "success" for job in jobs):
    raise SystemExit("HOLD: all four exact-commit Full suite jobs must succeed")
PY
printf 'SHIP %s\n' "$revision"
