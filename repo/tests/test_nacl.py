import subprocess, sys, os

def test_nacl_sample_packets_pass():
    root = os.path.dirname(os.path.dirname(__file__))
    r = subprocess.run([sys.executable, "tools/nacl_sim.py",
                         "network/nacl.json", "network/packets_sample.jsonl", "--check"],
                        cwd=root, capture_output=True, text=True)
    assert "6 / 6" in r.stdout or "100.0%" in r.stdout
