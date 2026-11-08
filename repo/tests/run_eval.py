"""Load a downloaded model directory and generate validation predictions."""
import argparse
import json

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ap = argparse.ArgumentParser()
ap.add_argument("--model-dir", required=True)
ap.add_argument("--validation", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--max-new-tokens", type=int, default=64)
args = ap.parse_args()

tok = AutoTokenizer.from_pretrained(args.model_dir)
model = AutoModelForCausalLM.from_pretrained(args.model_dir)
model.eval()

with open(args.validation) as f, open(args.out, "w") as out:
    for line in f:
        if not line.strip():
            continue
        rec = json.loads(line)
        prompt = f"Command: {rec['text']}\nJSON:"
        inputs = tok(prompt, return_tensors="pt")
        with torch.no_grad():
            gen = model.generate(**inputs, max_new_tokens=args.max_new_tokens,
                                  do_sample=False, pad_token_id=tok.eos_token_id)
        full = tok.decode(gen[0], skip_special_tokens=True)
        pred = full[len(prompt):].strip()
        out.write(json.dumps({"id": rec["id"], "prediction": pred}) + "\n")
