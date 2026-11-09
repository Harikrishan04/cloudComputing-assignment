import json
import os
import socket
import threading

import boto3
import torch
from fastapi import FastAPI, Response
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_URI = os.environ["MODEL_URI"]            # e.g. s3://models/v1/
MODEL_VERSION = os.environ["MODEL_VERSION"]    # e.g. v1
S3_ENDPOINT = os.environ["S3_ENDPOINT"]
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "64"))
FAULT_INJECT = os.environ.get("FAULT_INJECT", "0") == "1"

S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")

with open(os.environ.get("SCHEMA_PATH", "/app/schema.json")) as f:
    SCHEMA = json.load(f)
VALID_KEYS = set(SCHEMA["keys"])
VALID_INTENTS = set(SCHEMA["intents"])

POD_NAME = os.environ.get("POD_NAME", socket.gethostname())

app = FastAPI()
_state = {"ready": False, "model": None, "tokenizer": None}


def _download_model():
    bucket, prefix = MODEL_URI.replace("s3://", "").split("/", 1)
    s3 = boto3.client(
        "s3", endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY, aws_secret_access_key=S3_SECRET_KEY,
    )
    local_dir = "/tmp/model"
    os.makedirs(local_dir, exist_ok=True)
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            fname = key[len(prefix):].lstrip("/")
            if not fname:
                continue
            dest = os.path.join(local_dir, fname)
            os.makedirs(os.path.dirname(dest) or local_dir, exist_ok=True)
            s3.download_file(bucket, key, dest)

    tokenizer = AutoTokenizer.from_pretrained(local_dir)
    model = AutoModelForCausalLM.from_pretrained(local_dir)
    model.eval()
    _state["tokenizer"] = tokenizer
    _state["model"] = model
    _state["ready"] = True
    print("Model loaded and ready.")


@app.on_event("startup")
def startup():
    threading.Thread(target=_download_model, daemon=True).start()


class ParseRequest(BaseModel):
    text: str


def validate(obj) -> bool:
    if not isinstance(obj, dict) or set(obj.keys()) != VALID_KEYS:
        return False
    if obj["intent"] not in VALID_INTENTS:
        return False
    for k in ("date", "time", "place"):
        if obj[k] is not None and not isinstance(obj[k], str):
            return False
    return True


def run_model(text: str) -> str:
    tokenizer = _state["tokenizer"]
    model = _state["model"]
    prompt = f"Command: {text}\nJSON:"
    inputs = tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False, pad_token_id=tokenizer.eos_token_id,
        )
    full = tokenizer.decode(out[0], skip_special_tokens=True)
    gen = full[len(prompt):].strip()
    # keep only up to the first closing brace that balances the first opening brace
    if "{" in gen:
        start = gen.index("{")
        depth = 0
        for i, ch in enumerate(gen[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return gen[start:i + 1]
    return gen


@app.post("/parse")
def parse(req: ParseRequest, response: Response):
    response.headers["X-Model-Version"] = MODEL_VERSION
    response.headers["X-Served-By"] = POD_NAME

    if FAULT_INJECT:
        raw = "not json"
    else:
        raw = run_model(req.text)

    try:
        obj = json.loads(raw)
    except Exception:
        response.status_code = 500
        return {"error": "invalid_model_output"}

    if not validate(obj):
        response.status_code = 500
        return {"error": "invalid_model_output"}

    return obj


@app.get("/healthz")
def healthz():
    return {"status": "alive"}


@app.get("/readyz")
def readyz(response: Response):
    if not _state["ready"]:
        response.status_code = 503
        return {"status": "loading"}
    return {"status": "ready"}
