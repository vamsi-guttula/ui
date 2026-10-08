# Email spam/ham classifier

A small, dependency-free workflow that reads email and labels each message as
`spam` or `ham` (legitimate). It uses a multinomial Naive Bayes model, so it
runs anywhere Python 3.10+ is installed and needs no API keys.

## Files

| Path | Purpose |
| --- | --- |
| `classifier.py` | Training, CSV labelling, .eml classification, and IMAP fetch (CLI) |
| `test_classifier.py` | Unit tests (run with `python -m unittest -v test_classifier`) |
| `data/sample_train.csv` | Tiny example training set. Replace with real labelled mail. |
| `../../.github/workflows/email-classifier.yml` | Hourly + manual GitHub Actions run |

## Quick start

```bash
cd tools/email-classifier

# 1. Train a model from labelled data (columns: label,text; label is spam or ham)
python classifier.py train --data data/sample_train.csv --model model.json

# 2. Label emails stored in a CSV (your emails, one per row)
python classifier.py label-csv --model model.json \
  --input my_emails.csv --output my_emails_labelled.csv \
  --text-columns subject body

# 2b. Classify .eml files exported from your mail client
python classifier.py classify --model model.json message1.eml message2.eml

# ...or pipe a single raw message in
cat message.eml | python classifier.py classify --model model.json

# 3. Pull unread mail over IMAP and classify it (password read from env)
IMAP_PASSWORD='app-password' python classifier.py fetch \
  --model model.json --host imap.gmail.com --user you@example.com
```

Each result is one JSON line:

```json
{"message": "uid:42", "label": "spam", "spam_probability": 0.9981}
```

Use `--threshold 0.9` on `classify` or `fetch` to be more conservative about
labelling mail as spam.

## Automation

`.github/workflows/email-classifier.yml` runs the tests, trains the model, and
classifies unread mail hourly, or on demand from the Actions tab. Add these
repository secrets first:

- `IMAP_HOST` (e.g. `imap.gmail.com`)
- `IMAP_USER`
- `IMAP_PASSWORD` (use an app password, not your main password)

The fetch step only reads mail (`BODY.PEEK`), so it does not mark messages as
read. It reports labels in the job log and does not move or delete anything.

## Accuracy notes

- The bundled `sample_train.csv` has 24 examples. It is enough to test the
  pipeline but not to trust the labels. For real use, train on a few thousand
  labelled messages from your own mailbox, or from a public corpus such as
  SpamAssassin or Enron-Spam.
- Naive Bayes is fast and explainable. For higher accuracy on varied mail,
  consider an LLM-based classifier or a stronger model like logistic regression
  on TF-IDF features. The `classify` interface would stay the same.
- Review the threshold against false positives. Labelling a real message as
  spam costs more than letting a spam message through.
