#!/usr/bin/env python3
"""A stand-in member CLI for unit tests. Reads its prompt on stdin.

usage: fake_member.py MODEL [--new | --resume ID] [--writes]

It prints {"answer": ..., "session": ...}. A session is a file in
$FAKE_SESSIONS that holds the tasks of earlier calls, so a resumed call can
report what it remembers. Directives in the task text:
  SLEEP <seconds>   wait before answering
  FAIL              exit with status 3
  SILENT            exit 0 with an empty answer
"""
import json
import os
import sys
import time
import uuid

args = sys.argv[1:]
model = args.pop(0)
session = None
if "--resume" in args:
    session = args[args.index("--resume") + 1]
elif "--new" in args:
    session = uuid.uuid4().hex
prompt = sys.stdin.read()
task = prompt.split("Task:\n", 1)[-1].split("\n\n", 1)[0]
words = task.split()

remembered = []
if session:
    store = os.path.join(os.environ["FAKE_SESSIONS"], session)
    if os.path.exists(store):
        remembered = open(store).read().splitlines()
    with open(store, "a") as handle:
        handle.write(task + "\n")

if words[:1] == ["SLEEP"]:
    time.sleep(float(words[1]))
if words[:1] == ["FAIL"]:
    print("deliberate failure", file=sys.stderr)
    sys.exit(3)
answer = "" if words[:1] == ["SILENT"] else (
    f"model={model} writes={'--writes' in args} remembered={'|'.join(remembered)} "
    f"member={os.environ.get('FIXER_MEMBER')} cwd={os.getcwd()} pwd={os.environ.get('PWD')}\n"
    f"PROMPT<<{prompt}>>")
print(json.dumps({"answer": answer, "session": session}))
