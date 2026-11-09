import json, subprocess, sys, os, tempfile

def test_clean_rejects_invalid_json(tmp_path):
    shard = tmp_path / "shard-0.jsonl"
    shard.write_text(json.dumps({"id": "C0001", "text": "x", "teacher_raw": "not json"}) + "\n")
    pool = tmp_path / "pool.jsonl"
    pool.write_text(json.dumps({"id": "C0001", "text": "x"}) + "\n")
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"keys": ["intent","date","time","place"],
                                   "intents": ["alarm_set"]}))
    out = tmp_path / "train.jsonl"
    r = subprocess.run([sys.executable, "worker/clean.py",
                         "--shards-glob", str(shard), "--commands-pool", str(pool),
                         "--schema", str(schema), "--out", str(out)],
                        cwd=os.path.dirname(os.path.dirname(__file__)),
                        capture_output=True, text=True)
    assert "rejected (a)" in r.stdout
    assert "kept                        : 0" in r.stdout
