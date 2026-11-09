# AI_USE.md

AI tools used: Claude (Anthropic).

## What it was used for
- Scaffolding boilerplate code: the FastAPI service, the worker/clean.py cleaning
  script, Kubernetes manifests, the GitHub Actions workflow, and the Makefile.
- Working out the subnetting arithmetic for Task 5 and cross-checking it against
  `ipaddress` library output.
- Drafting this repository's structure and the README's run order.

## How it was checked
- Every script was run against the kit's own tools (`nacl_sim.py`, `score.py`,
  `pytest`) before being trusted; the NACL was verified to score 6/6 on
  `packets_sample.jsonl`.
- The subnet table was independently recomputed with Python's `ipaddress` module
  rather than taken on faith.
- Training and deployment were executed and the real logs, loss curves, and score
  reports in `results/` are from actual runs on my machine/Codespace, not generated
  text — the AI did not produce any of the measured numbers in the report.
- All conceptual explanations (sequence-level vs logit-based distillation, NACL
  statefulness, etc.) were cross-checked against the assigned readings (Kim & Rush
  2016; the PyTorch KD tutorial) before being included in the report.
