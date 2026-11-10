"""
Shard worker: reads commands_pool.jsonl, takes every line whose index % SHARD_COUNT == SHARD_INDEX,
sends each to the Ollama teacher (phi3.5) with the fixed prompt, and writes raw replies to object storage.

Env vars required:
  SHARD_INDEX     e.g. 0
  SHARD_COUNT     e.g. 2
  OLLAMA_HOST     e.g. http://localhost:11434  (default)
  S3_ENDPOINT     e.g. http://localhost:8333   (SeaweedFS S3 gateway)
  S3_ACCESS_KEY / S3_SECRET_KEY
  INPUT_PATH      local path to commands_pool.jsonl (downloaded first, or mounted)
  OUTPUT_BUCKET   default "datasets"
  OUTPUT_KEY      default f"teacher/shard-{SHARD_INDEX}.jsonl"
"""
import json
import os
import sys
import time
from pathlib import Path

import boto3
import requests

SHARD_INDEX = int(os.environ["SHARD_INDEX"])
SHARD_COUNT = int(os.environ["SHARD_COUNT"])
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
S3_ENDPOINT = os.environ["S3_ENDPOINT"]
S3_ACCESS_KEY = os.environ["S3_ACCESS_KEY"]
S3_SECRET_KEY = os.environ["S3_SECRET_KEY"]
INPUT_PATH = os.environ.get("INPUT_PATH", "/data/commands_pool.jsonl")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "datasets")
OUTPUT_KEY = os.environ.get("OUTPUT_KEY", f"teacher/shard-{SHARD_INDEX}.jsonl")
PROMPT_PATH = os.environ.get(
    "PROMPT_PATH",
    str(Path(__file__).resolve().parents[1] / "prompts" / "teacher_prompt.txt"),
)
MODEL = "phi3.5"
LIMIT = int(os.environ.get("LIMIT", "0"))

with open(PROMPT_PATH) as f:
    PROMPT_TEMPLATE = f.read()

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
)


def call_teacher(command_text: str) -> str:
    prompt = PROMPT_TEMPLATE.replace("{COMMAND}", command_text)
    resp = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
                "seed": 42,
                "num_predict": 48,
                "stop": ["\n\n", "```"],
                "num_ctx": 512,
            },
        },
        timeout=240,
    )
    resp.raise_for_status()
    raw = resp.json()["response"].strip()
    if "{" in raw:
        start = raw.index("{")
        depth = 0
        for i, ch in enumerate(raw[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return raw[start:i + 1]
    return raw


def main():
    lines = []
    with open(INPUT_PATH) as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            if i % SHARD_COUNT == SHARD_INDEX:
                lines.append((i, json.loads(line)))
                if LIMIT and len(lines) >= LIMIT:
                    break

    print(f"[shard {SHARD_INDEX}/{SHARD_COUNT}] processing {len(lines)} commands")

    out_path = f"/tmp/shard-{SHARD_INDEX}.jsonl"
    with open(out_path, "w") as out:
        for n, (idx, rec) in enumerate(lines):
            cid = rec["id"]
            text = rec["text"]
            print(f"  [{n + 1}/{len(lines)}] {cid}: calling teacher...", flush=True)
            for attempt in range(3):
                try:
                    raw = call_teacher(text)
                    break
                except (requests.RequestException, KeyError, ValueError) as e:
                    print(f"  retry {cid}: {e}", file=sys.stderr)
                    time.sleep(2)
            else:
                raw = ""
            out.write(json.dumps({"id": cid, "text": text, "teacher_raw": raw}) + "\n")
            out.flush()
            print(f"  [{n + 1}/{len(lines)}] {cid} done -> {raw[:60]}")

    s3.upload_file(out_path, OUTPUT_BUCKET, OUTPUT_KEY)
    print(f"[shard {SHARD_INDEX}] uploaded to s3://{OUTPUT_BUCKET}/{OUTPUT_KEY}")


if __name__ == "__main__":
    main()
