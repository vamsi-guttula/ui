#!/usr/bin/env python3
"""Spam/ham email classifier.

A multinomial Naive Bayes model using only the Python standard library.

Subcommands:
  train     Train a model from a CSV file with `label,text` columns.
  classify  Classify raw .eml files (or a raw message on stdin).
  fetch     Pull unread messages from an IMAP mailbox and classify them.
"""
from __future__ import annotations

import argparse
import csv
import imaplib
import json
import math
import os
import re
import sys
from collections import Counter
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Iterable

LABELS = ("ham", "spam")
TOKEN_RE = re.compile(r"[a-z0-9]+|[$!]")
HTML_TAG_RE = re.compile(r"<[^>]+>")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def extract_text(raw: bytes) -> str:
    """Return the subject and plain-text body of a raw RFC 822 message."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = str(msg.get("subject", ""))
    try:
        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body is not None else ""
        if body is not None and body.get_content_type() == "text/html":
            text = HTML_TAG_RE.sub(" ", text)
    except (LookupError, ValueError, KeyError):
        text = ""
    return f"{subject}\n{text}"


class NaiveBayes:
    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.doc_counts: Counter[str] = Counter()
        self.token_counts: dict[str, Counter[str]] = {}
        self.vocab: set[str] = set()

    def train(self, examples: Iterable[tuple[str, str]]) -> None:
        for label, text in examples:
            if label not in LABELS:
                raise ValueError(f"unknown label {label!r}, expected one of {LABELS}")
            tokens = tokenize(text)
            self.doc_counts[label] += 1
            self.token_counts.setdefault(label, Counter()).update(tokens)
            self.vocab.update(tokens)

    def predict_proba(self, text: str) -> dict[str, float]:
        """Return the posterior probability of each label for `text`."""
        if not self.doc_counts:
            raise RuntimeError("model has not been trained")
        total_docs = sum(self.doc_counts.values())
        vocab_size = len(self.vocab)
        tokens = [t for t in tokenize(text) if t in self.vocab]

        log_scores = {}
        for label, n_docs in self.doc_counts.items():
            counts = self.token_counts[label]
            total_tokens = sum(counts.values())
            score = math.log(n_docs / total_docs)
            for token in tokens:
                score += math.log(
                    (counts[token] + self.alpha) / (total_tokens + self.alpha * vocab_size)
                )
            log_scores[label] = score

        top = max(log_scores.values())
        exps = {label: math.exp(s - top) for label, s in log_scores.items()}
        total = sum(exps.values())
        return {label: value / total for label, value in exps.items()}

    def classify(self, text: str, threshold: float = 0.5) -> tuple[str, float]:
        """Return (label, spam_probability). Spam when P(spam) >= threshold."""
        spam_p = self.predict_proba(text).get("spam", 0.0)
        return ("spam" if spam_p >= threshold else "ham"), spam_p

    def save(self, path: Path) -> None:
        data = {
            "alpha": self.alpha,
            "doc_counts": dict(self.doc_counts),
            "token_counts": {label: dict(c) for label, c in self.token_counts.items()},
        }
        path.write_text(json.dumps(data))

    @classmethod
    def load(cls, path: Path) -> "NaiveBayes":
        data = json.loads(path.read_text())
        model = cls(alpha=data["alpha"])
        model.doc_counts = Counter(data["doc_counts"])
        model.token_counts = {label: Counter(c) for label, c in data["token_counts"].items()}
        model.vocab = {token for c in model.token_counts.values() for token in c}
        return model


def load_training_csv(path: Path) -> list[tuple[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [(row["label"].strip().lower(), row["text"]) for row in reader]


def cmd_train(args: argparse.Namespace) -> int:
    model = NaiveBayes(alpha=args.alpha)
    examples = load_training_csv(Path(args.data))
    model.train(examples)
    model.save(Path(args.model))
    counts = dict(model.doc_counts)
    print(f"trained on {len(examples)} examples {counts}; vocab={len(model.vocab)}")
    print(f"model written to {args.model}")
    return 0


def emit(name: str, raw: bytes, model: NaiveBayes, threshold: float) -> dict:
    label, spam_p = model.classify(extract_text(raw), threshold)
    result = {"message": name, "label": label, "spam_probability": round(spam_p, 4)}
    print(json.dumps(result))
    return result


def cmd_classify(args: argparse.Namespace) -> int:
    model = NaiveBayes.load(Path(args.model))
    if not args.paths:
        emit("<stdin>", sys.stdin.buffer.read(), model, args.threshold)
        return 0
    for name in args.paths:
        if name == "-":
            emit("<stdin>", sys.stdin.buffer.read(), model, args.threshold)
        else:
            emit(name, Path(name).read_bytes(), model, args.threshold)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    password = os.environ.get("IMAP_PASSWORD")
    if not password:
        print("IMAP_PASSWORD environment variable is required", file=sys.stderr)
        return 2

    model = NaiveBayes.load(Path(args.model))
    imap = imaplib.IMAP4_SSL(args.host, args.port)
    try:
        imap.login(args.user, password)
        imap.select(args.folder, readonly=True)
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            print("IMAP search failed", file=sys.stderr)
            return 1
        uids = data[0].split()[-args.limit :]
        for uid in uids:
            # BODY.PEEK leaves the \Seen flag untouched.
            status, parts = imap.fetch(uid, "(BODY.PEEK[])")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                print(f"could not fetch message {uid.decode()}", file=sys.stderr)
                continue
            emit(f"uid:{uid.decode()}", parts[0][1], model, args.threshold)
    finally:
        try:
            imap.logout()
        except imaplib.IMAP4.error:
            pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_train = sub.add_parser("train", help="train a model from a labelled CSV")
    p_train.add_argument("--data", required=True, help="CSV with label,text columns")
    p_train.add_argument("--model", required=True, help="output model JSON path")
    p_train.add_argument("--alpha", type=float, default=1.0, help="Laplace smoothing (default 1.0)")
    p_train.set_defaults(func=cmd_train)

    threshold_help = "P(spam) at or above this is labelled spam (default 0.5)"

    p_classify = sub.add_parser("classify", help="classify .eml files or stdin")
    p_classify.add_argument("--model", required=True)
    p_classify.add_argument("--threshold", type=float, default=0.5, help=threshold_help)
    p_classify.add_argument("paths", nargs="*", help=".eml files; '-' or no paths reads stdin")
    p_classify.set_defaults(func=cmd_classify)

    p_fetch = sub.add_parser("fetch", help="classify unread IMAP messages (password in IMAP_PASSWORD)")
    p_fetch.add_argument("--model", required=True)
    p_fetch.add_argument("--host", required=True)
    p_fetch.add_argument("--port", type=int, default=993)
    p_fetch.add_argument("--user", required=True)
    p_fetch.add_argument("--folder", default="INBOX")
    p_fetch.add_argument("--limit", type=int, default=50, help="max unread messages to process")
    p_fetch.add_argument("--threshold", type=float, default=0.5, help=threshold_help)
    p_fetch.set_defaults(func=cmd_fetch)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
