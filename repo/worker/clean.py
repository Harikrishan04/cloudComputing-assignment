"""
Reads all teacher shard outputs from object storage (or a local glob), applies the
cleaning rules from Section 5.1 (a)-(e) of the assignment, writes datasets/v1/train.jsonl
(id order) + its SHA-256 checksum, and prints the counts table needed for the report.

Usage:
  python worker/clean.py --shards-glob "shards/*.jsonl" --schema data/schema.json \
      --out datasets/v1/train.jsonl
  (then separately upload train.jsonl + train.sha256 to the 'datasets' bucket under v1/)
"""
import argparse
import glob
import hashlib
import json
import sys


def load_schema(path):
    with open(path) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards-glob", required=True, help="glob matching local shard-*.jsonl files")
    ap.add_argument("--commands-pool", default="data/commands_pool.jsonl")
    ap.add_argument("--schema", default="data/schema.json")
    ap.add_argument("--out", default="datasets/v1/train.jsonl")
    args = ap.parse_args()

    schema = load_schema(args.schema)
    valid_keys = set(schema["keys"])
    valid_intents = set(schema["intents"])

    # original command text by id, to check "slot value must appear in the command"
    commands = {}
    with open(args.commands_pool) as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                commands[rec["id"]] = rec["text"].lower()

    total_in = 0
    rejected_a = 0  # not valid JSON
    rejected_b = 0  # wrong keys
    rejected_c = 0  # bad intent
    rejected_d = 0  # slot not null and not substring of command
    seen_by_text = {}  # text -> smallest id kept
    kept_records = {}  # id -> record

    files = sorted(glob.glob(args.shards_glob))
    if not files:
        print(f"No files matched {args.shards_glob}", file=sys.stderr)
        sys.exit(1)

    for fp in files:
        with open(fp) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_in += 1
                outer = json.loads(line)  # the shard line itself is well-formed JSON
                cid = outer["id"]
                text = outer["text"]
                raw = outer["teacher_raw"]

                try:
                    parsed = json.loads(raw)
                except Exception:
                    rejected_a += 1
                    continue

                if not isinstance(parsed, dict) or set(parsed.keys()) != valid_keys:
                    rejected_b += 1
                    continue

                if parsed["intent"] not in valid_intents:
                    rejected_c += 1
                    continue

                ok_slots = True
                cmd_lower = commands.get(cid, text).lower()
                for slot in ("date", "time", "place"):
                    val = parsed[slot]
                    if val is None:
                        continue
                    if not isinstance(val, str) or val.strip() == "":
                        ok_slots = False
                        break
                    if val.strip().lower() not in cmd_lower:
                        ok_slots = False
                        break
                if not ok_slots:
                    rejected_d += 1
                    continue

                kept_records[cid] = {
                    "id": cid,
                    "text": text,
                    "intent": parsed["intent"],
                    "date": parsed["date"],
                    "time": parsed["time"],
                    "place": parsed["place"],
                }
                seen_by_text.setdefault(text, []).append(cid)

    # duplicate commands: keep smallest id per identical text
    duplicates = 0
    final = {}
    for text, ids in seen_by_text.items():
        ids_sorted = sorted(ids)
        keep = ids_sorted[0]
        duplicates += len(ids_sorted) - 1
        final[keep] = kept_records[keep]

    ordered_ids = sorted(final.keys())
    out_lines = [json.dumps(final[i], sort_keys=False) for i in ordered_ids]

    import os
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        for line in out_lines:
            f.write(line + "\n")

    sha = hashlib.sha256()
    with open(args.out, "rb") as f:
        sha.update(f.read())
    checksum_path = args.out.replace(".jsonl", ".sha256")
    with open(checksum_path, "w") as f:
        f.write(sha.hexdigest() + "\n")

    kept = len(final)
    print("=== Cleaning report ===")
    print(f"input records              : {total_in}")
    print(f"rejected (a) invalid JSON   : {rejected_a}")
    print(f"rejected (b) wrong keys     : {rejected_b}")
    print(f"rejected (c) bad intent     : {rejected_c}")
    print(f"rejected (d) bad slot value : {rejected_d}")
    print(f"duplicates removed          : {duplicates}")
    print(f"kept                        : {kept}")
    check = rejected_a + rejected_b + rejected_c + rejected_d + duplicates + kept
    print(f"sum check (should = input)  : {check} vs input {total_in} -> {'OK' if check == total_in else 'MISMATCH'}")
    print(f"wrote {args.out}")
    print(f"sha256: {sha.hexdigest()}  -> {checksum_path}")


if __name__ == "__main__":
    main()
