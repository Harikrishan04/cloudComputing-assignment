"""
Fine-tunes EleutherAI/pythia-70m on teacher-generated (command -> JSON) pairs.
Sequence-level distillation: train the student to produce the teacher's exact text output.

Usage:
  python training/train.py --train datasets/v1/train.jsonl --config training/config.yaml \
      --out models/v1 --subset 1500

  python training/train.py --train datasets/v1/train.jsonl --config training/config.yaml \
      --out models/v2 --subset 1500 --seed 43   # second version for Task 4
"""
import argparse
import json
import os
import random
import csv

import yaml
import torch
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    DataCollatorForLanguageModeling,
)


def set_seed(seed):
    random.seed(seed)
    torch.manual_seed(seed)


class CommandJsonDataset(Dataset):
    def __init__(self, records, tokenizer, max_len):
        self.examples = []
        for r in records:
            target_json = json.dumps(
                {"intent": r["intent"], "date": r["date"], "time": r["time"], "place": r["place"]}
            )
            text = f"Command: {r['text']}\nJSON: {target_json}{tokenizer.eos_token}"
            enc = tokenizer(text, truncation=True, max_length=max_len, padding="max_length")
            enc["labels"] = enc["input_ids"].copy()
            self.examples.append(enc)

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        return {k: torch.tensor(v) for k, v in self.examples[idx].items()}


class LossLogger:
    """Collects one average loss value per epoch into loss.csv"""

    def __init__(self, path):
        self.path = path
        self.rows = []

    def log(self, epoch, loss):
        self.rows.append((epoch, loss))

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["epoch", "loss"])
            for e, l in self.rows:
                w.writerow([e, l])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--config", default="training/config.yaml")
    ap.add_argument("--out", required=True, help="output dir for model+tokenizer")
    ap.add_argument("--subset", type=int, default=None, help="use only first N records")
    ap.add_argument("--seed", type=int, default=None, help="override seed in config.yaml")
    ap.add_argument("--loss-csv", default="training/loss.csv")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    seed = args.seed if args.seed is not None else cfg["seed"]
    set_seed(seed)

    records = []
    with open(args.train) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    n = args.subset if args.subset else min(1500, len(records))
    records = records[:n]
    print(f"Training on {len(records)} records (seed={seed})")

    tokenizer = AutoTokenizer.from_pretrained(cfg["model_name"])
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(cfg["model_name"])

    dataset = CommandJsonDataset(records, tokenizer, cfg["max_seq_length"])

    logger = LossLogger(args.loss_csv)

    class LoggingTrainer(Trainer):
        def log(self, logs, start_time=None):
            super().log(logs)
            if "loss" in logs and "epoch" in logs:
                logger.log(logs["epoch"], logs["loss"])

    training_args = TrainingArguments(
        output_dir="/tmp/train_run",
        num_train_epochs=cfg["num_epochs"],
        per_device_train_batch_size=cfg["batch_size"],
        learning_rate=cfg["learning_rate"],
        logging_strategy="epoch",
        save_strategy="no",
        report_to=[],
        seed=seed,
        use_cpu=True,
    )

    trainer = LoggingTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )
    trainer.train()

    os.makedirs(args.out, exist_ok=True)
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    logger.save()
    print(f"Saved model+tokenizer to {args.out}, loss log to {args.loss_csv}")


if __name__ == "__main__":
    main()
