.PHONY: up down train train-subset build-image eval ci-local

up:
	k3d cluster create --config cluster/k3d.yaml
	kubectl apply -f k8s/namespace-data.yaml -f k8s/namespace-pipeline.yaml -f k8s/namespace-app.yaml
	# (SeaweedFS deploy + model build + docker import happens as separate documented steps; see README)
	kubectl apply -f k8s/secret.yaml -f k8s/deployment.yaml -f k8s/service.yaml -f k8s/ingress.yaml -f k8s/hpa.yaml

down:
	k3d cluster delete cloud-mini

SUBSET ?= 1500
train:
	python training/train.py --train datasets/v1/train.jsonl --config training/config.yaml --out models/v1 --subset $(SUBSET)

build-image:
	docker build -f service/Dockerfile -t parser-service:v1 .

eval:
	python tools/score.py results/predictions.jsonl data/validation.jsonl --out results/report.json --min-validity 95
