# Cloud Computing Mini Project — Runbook (GitHub Codespaces)

This repo was scaffolded to run entirely inside a **GitHub Codespace** (free tier:
4 cores / 16 GB RAM / 32 GB disk is enough). Everything below is one shell, no
local install needed except a browser. (Original kit instructions preserved in
`KIT_README_ORIGINAL.md`.)

## 0. Open a Codespace
1. Push this repo to GitHub.
2. On the repo page: **Code → Codespaces → Create codespace on main**.
3. Pick the default machine type (or the biggest free one offered).

## 1. Install tooling inside the Codespace (one time)
```bash
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
curl -fsSL https://ollama.com/install.sh | sh
pip install -r service/requirements.txt pytest ruff boto3 pyyaml
# Docker is already present in Codespaces.
```

## 2. Task 1 — cluster, object storage, teacher labelling
```bash
k3d cluster create --config cluster/k3d.yaml
kubectl apply -f k8s/namespace-data.yaml -f k8s/namespace-pipeline.yaml -f k8s/namespace-app.yaml

# Deploy SeaweedFS (simplest: run its S3 gateway as a Deployment in ns 'data' — see
# https://github.com/seaweedfs/seaweedfs/wiki/Docker-Quick-Start for a manifest you
# can adapt; expose it as a Service named seaweedfs-s3 on port 8333).

# Create buckets + upload the pool (after port-forwarding the S3 gateway to localhost:8333):
aws --endpoint-url http://localhost:8333 s3 mb s3://datasets
aws --endpoint-url http://localhost:8333 s3 mb s3://models
aws --endpoint-url http://localhost:8333 s3 cp data/commands_pool.jsonl s3://datasets/

# Pull the teacher model
ollama pull phi3.5

# Run >=2 workers with different shards (two terminals, or background one):
SHARD_INDEX=0 SHARD_COUNT=2 S3_ENDPOINT=http://localhost:8333 \
  S3_ACCESS_KEY=<key> S3_SECRET_KEY=<secret> INPUT_PATH=data/commands_pool.jsonl \
  python worker/worker.py &
SHARD_INDEX=1 SHARD_COUNT=2 S3_ENDPOINT=http://localhost:8333 \
  S3_ACCESS_KEY=<key> S3_SECRET_KEY=<secret> INPUT_PATH=data/commands_pool.jsonl \
  python worker/worker.py &
wait

# Clean the shard outputs into datasets/v1/train.jsonl (download the shards locally first):
python worker/clean.py --shards-glob "shards/*.jsonl" --out datasets/v1/train.jsonl
# then: aws --endpoint-url http://localhost:8333 s3 cp datasets/v1/train.jsonl s3://datasets/v1/
#       aws --endpoint-url http://localhost:8333 s3 cp datasets/v1/train.sha256 s3://datasets/v1/
```

## 3. Task 2 — train the student
```bash
make train SUBSET=50     # quick smoke test
make train                # full run on all cleaned records -> models/v1
python training/train.py --train datasets/v1/train.jsonl --config training/config.yaml \
    --out models/v2 --seed 43     # second version for Task 4

# upload both to the models bucket + checksum, and attach as a GitHub Release asset
sha256sum models/v1/* > models/v1/model.sha256

# score all three models on validation.jsonl, save to results/
python tools/score.py results/teacher_predictions.jsonl data/validation.jsonl --out results/teacher_validation.json
python tools/score.py results/base_predictions.jsonl data/validation.jsonl --out results/base_report.json
python tools/score.py results/student_predictions.jsonl data/validation.jsonl --out results/student_report.json
```

## 4. Task 3 — containerise
```bash
docker build -f service/Dockerfile -t parser-service:v1 .
docker images parser-service:v1   # check size <= 2GB
docker run --rm -p 8000:8000 --cpus=1 --memory=1g \
  -e MODEL_URI=s3://models/v1/ -e MODEL_VERSION=v1 \
  -e S3_ENDPOINT=http://host.docker.internal:8333 -e MAX_NEW_TOKENS=64 \
  -e S3_ACCESS_KEY=<key> -e S3_SECRET_KEY=<secret> parser-service:v1
# then send 50 requests and watch `docker stats` for peak memory
```

## 5. Task 4 — deploy, scale, update, recover
```bash
k3d image import parser-service:v1 -c cloud-mini
kubectl create secret generic s3-creds -n app \
  --from-literal=S3_ACCESS_KEY=<key> --from-literal=S3_SECRET_KEY=<secret>
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml -f k8s/ingress.yaml -f k8s/hpa.yaml

# load test through the Ingress
pip install locust
locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
  --host http://localhost:8080 --csv results/loadtest

# rolling update, recovery, cold start: see Task 4 steps 5-8 in the assignment PDF;
# each just needs `kubectl set env`, `kubectl rollout undo`, `kubectl delete pod`, etc.
```

## 6. Task 5 — subnets & NACL (already done)
See `network/subnets.md` for the worked table and `network/nacl.json` for the rules.
Verify:
```bash
python tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check
```

## 7. Task 6 — CI/CD
The repository-root `.github/workflows/ci.yml` runs lint, unit tests, and a
secret scan on pushes. After publishing the `v1` release asset, trigger
`workflow_dispatch` with `model_release_tag=v1` to run evaluation and the 95%
JSON-validity quality gate. To demonstrate gate failure, dispatch it with a
release tag containing an untrained model.
```bash
pytest tests/ -v
ruff check service worker training tests
```

## 8. Task 7 — performance & cost
Run the same Locust command as Task 4 and `kubectl top pods` during the run; fill
the review table in `report/report.pdf` with the real numbers. The cost formula is
pre-wired to `data/rate_card.json`:
```
hourly cost of 2 replicas @ 1 vCPU / 1 GiB limits = 2 * (1*3.50 + 1*0.45) = INR 7.90/hr
cost per 1000 requests = 7.90 / (measured_rps * 3600) * 1000
```
Replace `measured_rps` with your real Locust throughput number.

## Teardown
```bash
make down
```

## Completed evidence

The full Kaggle labelling run produced 3,000 teacher responses. Cleaning kept
2,918 records: 6 were rejected for invalid intents, 26 for invalid slot values,
and 50 duplicate commands were removed. The sum check was 3,000/3,000. The
dataset checksum is recorded in `datasets/v1/train.sha256`.

The first Kaggle full-data checkpoint was invalid: all 70,426,624 parameters
were NaN and its validation output had 0% JSON validity. That failed checkpoint
is preserved under `models/kaggle-full-data-v1/` for diagnosis. The trainer was
updated to load float32 weights and refuse to save non-finite parameters. The
corrected model was trained on all 2,918 cleaned records, has finite weights,
and passes the 95% JSON-validity gate with 99% validity, 37% full-frame
accuracy, and no missing predictions. Its report and predictions are
`results/student_report.json` and `results/student_predictions.jsonl`; its
loss-by-epoch is in `training/loss.csv`. The deployable model is in
`models/v1/`, with checksums in `models/v1/model.sha256` and release archive
`results/models-v1.tar.gz`. The initial 50-record v1 checkpoint is retained in
`models/v1-subset50-backup/`.

The current evaluated artifacts are under `results/`:

- `base_report.json`, `student_report.json`, and `teacher_validation.json`
- `kaggle_full_data_report.json` and `kaggle_full_data_predictions.jsonl`
- `kaggle_full_data_health.json` (records the failed first Kaggle checkpoint)
- `loadtest_stats.csv`, `final_loadtest_stats.csv`, and `loadtest_headers.json`
- `v2_loadtest_stats.csv`
- `container_evidence.json`
- `cold_start_evidence.json`
- `cost_estimate.json`
- `report/report.pdf`
- `report/reflection.pdf`

The service is deployed with two ready replicas, `Never` image pull policy, and
`v1` restored after the model v2 rolling-update test. The SeaweedFS Kubernetes
deployment remains scaled to zero because the host S3 gateway is used with an
explicit `Endpoints` resource for stable local execution.
