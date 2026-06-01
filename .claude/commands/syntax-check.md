---
description: Syntax-check bot.py with py_compile
allowed-tools: Bash(python -m py_compile bot.py)
---

Run `python -m py_compile bot.py` and report PASS/FAIL with the full traceback on failure.

This is the minimum verification gate before claiming any `bot.py` change is done — there are no tests and no linter, so `py_compile` is the only static check. (A PostToolUse hook also runs this automatically after every edit to `bot.py`.)
