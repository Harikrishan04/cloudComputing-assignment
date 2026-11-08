import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "service"))

def test_validate_rejects_bad_keys(monkeypatch):
    os.environ.setdefault("MODEL_URI", "s3://models/v1/")
    os.environ.setdefault("MODEL_VERSION", "v1")
    os.environ.setdefault("S3_ENDPOINT", "http://localhost:8333")
    import app as svc
    assert svc.validate({"intent": "alarm_set", "date": None, "time": None, "place": None}) is True
    assert svc.validate({"intent": "alarm_set", "date": None, "time": None}) is False
    assert svc.validate({"intent": "not_a_real_intent", "date": None, "time": None, "place": None}) is False

def test_validate_rejects_non_string_slot():
    import app as svc
    assert svc.validate({"intent": "alarm_set", "date": 5, "time": None, "place": None}) is False
