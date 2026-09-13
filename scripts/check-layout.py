#!/usr/bin/env python3
"""Check the source boundary, host pin, and product E2E classification."""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
source = root / "src"


def git(*args: str, cwd: Path = root) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


for path in source.rglob("*.zig"):
    for imported in re.findall(r'@import\("([^\"]+)"\)', path.read_text()):
        if imported in {"std", "fx_orchestration_host"}:
            continue
        dependency = (path.parent / imported).resolve()
        if not dependency.is_relative_to(source) or not dependency.is_file():
            raise SystemExit(f"{path.relative_to(root)} imports outside Fixer's boundary: {imported}")

entry = git("ls-files", "--stage", "vendor/fx").split()
if len(entry) != 4 or entry[0] != "160000":
    raise SystemExit("vendor/fx must be a pinned Git submodule")
if git("rev-parse", "HEAD", cwd=root / "vendor/fx") != entry[1]:
    raise SystemExit("Host checkout differs from the pin; run git submodule update --init")
if git("status", "--porcelain", "--untracked-files=no", cwd=root / "vendor/fx"):
    raise SystemExit("Host has tracked edits; commit them in the support fork and update the pin")

manifest = json.loads((root / "scripts/pgso/corpus.json").read_text())
owners = list(manifest["intentional_exclusions"])
for section in ("scenarios", "verification_scenarios"):
    owners.extend(item["test_file"] for item in manifest[section] if "test_file" in item)
files = {path.name for path in (root / "tests/e2e").glob("*.test.ts")}
if set(owners) != files or any(count != 1 for count in Counter(owners).values()):
    raise SystemExit("Every product E2E file must have exactly one current PGSO classification")

print(f"Fixer source boundary, fx pin {entry[1]}, and E2E ownership verified")
