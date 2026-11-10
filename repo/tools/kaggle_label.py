"""Label command records with Phi-3.5 on a Kaggle GPU and resume from JSONL output."""
import argparse
import json
import os
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


def extract_json(text):
    start = text.find("{")
    if start < 0:
        return text.strip()

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", required=True, help="commands_pool.jsonl")
    parser.add_argument("--prompt", required=True, help="teacher_prompt.txt")
    parser.add_argument("--out", required=True, help="appendable raw labels JSONL")
    parser.add_argument("--model", default="microsoft/Phi-3.5-mini-instruct")
    parser.add_argument("--limit", type=int, default=0, help="optional maximum new records")
    args = parser.parse_args()

    if args.limit < 0:
        parser.error("--limit cannot be negative")

    with open(args.prompt, encoding="utf-8") as prompt_file:
        prompt_template = prompt_file.read()
    with open(args.pool, encoding="utf-8") as pool_file:
        records = [json.loads(line) for line in pool_file if line.strip()]

    completed = set()
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as output_file:
            for line_number, line in enumerate(output_file, 1):
                if line.strip():
                    try:
                        completed.add(json.loads(line)["id"])
                    except (json.JSONDecodeError, KeyError) as error:
                        raise ValueError(f"{args.out}:{line_number}: invalid checkpoint line") from error

    pending = [record for record in records if record["id"] not in completed]
    if args.limit:
        pending = pending[:args.limit]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    print(f"Device: {torch.cuda.get_device_name(0) if device == 'cuda' else 'CPU'}")
    print(f"Already labelled: {len(completed)}; remaining this run: {len(pending)}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=dtype,
        device_map="auto",
    )
    model.eval()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as output_file:
        for number, record in enumerate(pending, 1):
            prompt = prompt_template.replace("{COMMAND}", record["text"])
            messages = [{"role": "user", "content": prompt}]
            model_input = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            )
            model_input = {key: value.to(model.device) for key, value in model_input.items()}

            raw = ""
            for attempt in range(3):
                try:
                    with torch.inference_mode():
                        generated = model.generate(
                            **model_input,
                            max_new_tokens=96,
                            do_sample=False,
                            pad_token_id=tokenizer.eos_token_id,
                        )
                    new_tokens = generated[0, model_input["input_ids"].shape[1]:]
                    raw = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
                    raw = extract_json(raw)
                    break
                except (RuntimeError, ValueError) as error:
                    if attempt == 2:
                        raise RuntimeError(f"Failed to label {record['id']} after retries") from error
                    print(f"Retry {record['id']} ({attempt + 1}/3): {error}", flush=True)
                    time.sleep(2)

            output_file.write(json.dumps({
                "id": record["id"],
                "text": record["text"],
                "teacher_raw": raw,
            }, ensure_ascii=False) + "\n")
            output_file.flush()

            if number % 25 == 0 or number == len(pending):
                print(f"Progress: {number}/{len(pending)} this run", flush=True)


if __name__ == "__main__":
    main()
