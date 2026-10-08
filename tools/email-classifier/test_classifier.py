import contextlib
import csv
import io
import json
import os
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

import classifier
from classifier import NaiveBayes, extract_text, tokenize

HERE = Path(__file__).parent
SAMPLE = HERE / "data" / "sample_train.csv"


def make_eml(subject: str, body: str, html: bool = False) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "sender@example.com"
    msg["To"] = "you@example.com"
    if html:
        msg.set_content("placeholder")
        msg.replace_header("Content-Type", "text/html")
        msg.set_payload(f"<html><body><p>{body}</p></body></html>")
    else:
        msg.set_content(body)
    return msg.as_bytes()


def trained_model() -> NaiveBayes:
    model = NaiveBayes()
    model.train(classifier.load_training_csv(SAMPLE))
    return model


class TokenizeTests(unittest.TestCase):
    def test_lowercases_and_keeps_money_and_exclamation_signals(self):
        self.assertEqual(tokenize("WIN $500!!"), ["win", "$", "500", "!", "!"])


class ExtractTextTests(unittest.TestCase):
    def test_plain_text_includes_subject_and_body(self):
        text = extract_text(make_eml("Hello", "Body text here"))
        self.assertIn("Hello", text)
        self.assertIn("Body text here", text)

    def test_html_tags_are_stripped(self):
        text = extract_text(make_eml("Promo", "Buy <b>now</b>", html=True))
        self.assertIn("Buy", text)
        self.assertNotIn("<b>", text)


class NaiveBayesTests(unittest.TestCase):
    def test_obvious_spam_and_ham(self):
        model = trained_model()
        label, spam_p = model.classify("Claim your free $1000 prize, click now!!!")
        self.assertEqual(label, "spam")
        self.assertGreater(spam_p, 0.5)

        label, spam_p = model.classify("Can we move the team meeting to Tuesday?")
        self.assertEqual(label, "ham")
        self.assertLess(spam_p, 0.5)

    def test_probabilities_sum_to_one(self):
        probs = trained_model().predict_proba("some random words")
        self.assertAlmostEqual(sum(probs.values()), 1.0)

    def test_threshold_controls_label(self):
        model = trained_model()
        _, spam_p = model.classify("free prize")
        label, _ = model.classify("free prize", threshold=spam_p + 0.01)
        self.assertEqual(label, "ham")

    def test_unknown_label_is_rejected(self):
        with self.assertRaises(ValueError):
            NaiveBayes().train([("maybe", "text")])

    def test_untrained_model_refuses_to_predict(self):
        with self.assertRaises(RuntimeError):
            NaiveBayes().predict_proba("hello")

    def test_save_and_load_round_trip(self):
        model = trained_model()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            model.save(path)
            loaded = NaiveBayes.load(path)
        text = "Claim your free prize today"
        self.assertEqual(model.predict_proba(text), loaded.predict_proba(text))
        self.assertEqual(model.vocab, loaded.vocab)


class CliTests(unittest.TestCase):
    def test_train_then_classify_eml_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.json"
            spam_path = Path(tmp) / "spam.eml"
            ham_path = Path(tmp) / "ham.eml"
            spam_path.write_bytes(make_eml("WINNER", "Claim your free $1000 prize now!!!"))
            ham_path.write_bytes(make_eml("Lunch", "Are we still meeting for lunch tomorrow?"))

            self.assertEqual(
                classifier.main(["train", "--data", str(SAMPLE), "--model", str(model_path)]), 0
            )

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                classifier.main(["classify", "--model", str(model_path), str(spam_path), str(ham_path)])
            results = [json.loads(line) for line in out.getvalue().splitlines()]

        self.assertEqual([r["label"] for r in results], ["spam", "ham"])


class LabelCsvTests(unittest.TestCase):
    def test_reads_emails_from_csv_and_writes_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            model_path = tmp / "model.json"
            trained_model().save(model_path)
            input_path = tmp / "emails.csv"
            input_path.write_text(
                "id,subject,body\n"
                "1,WINNER,Claim your free $1000 prize now!!!\n"
                "2,Lunch,Are we still meeting for lunch tomorrow?\n",
                encoding="utf-8",
            )
            output_path = tmp / "labelled.csv"

            code = classifier.main([
                "label-csv", "--model", str(model_path), "--input", str(input_path),
                "--output", str(output_path), "--text-columns", "subject", "body",
            ])

            with output_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(code, 0)
        self.assertEqual([r["label"] for r in rows], ["spam", "ham"])
        self.assertEqual(rows[0]["id"], "1")
        self.assertIn("spam_probability", rows[0])

    def test_missing_text_column_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            model_path = tmp / "model.json"
            trained_model().save(model_path)
            input_path = tmp / "emails.csv"
            input_path.write_text("id,subject\n1,hi\n", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = classifier.main([
                    "label-csv", "--model", str(model_path), "--input", str(input_path),
                    "--output", str(tmp / "out.csv"),
                ])
        self.assertEqual(code, 2)
        self.assertIn("text", err.getvalue())


class FetchTests(unittest.TestCase):
    def test_fetch_classifies_unseen_messages_with_peek(self):
        spam_raw = make_eml("WINNER", "Claim your free $1000 prize now!!!")
        ham_raw = make_eml("Lunch", "Are we still meeting for lunch tomorrow?")
        imap = mock.MagicMock()
        imap.search.return_value = ("OK", [b"1 2"])
        imap.fetch.side_effect = [
            ("OK", [(b"1 (BODY[] {n})", spam_raw)]),
            ("OK", [(b"2 (BODY[] {n})", ham_raw)]),
        ]

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(classifier.imaplib, "IMAP4_SSL", return_value=imap), \
                mock.patch.dict(os.environ, {"IMAP_PASSWORD": "secret"}):
            model_path = Path(tmp) / "model.json"
            trained_model().save(model_path)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = classifier.main(
                    ["fetch", "--model", str(model_path), "--host", "imap.example.com", "--user", "me@example.com"]
                )

        self.assertEqual(code, 0)
        imap.login.assert_called_once_with("me@example.com", "secret")
        imap.search.assert_called_once_with(None, "UNSEEN")
        imap.fetch.assert_any_call(b"1", "(BODY.PEEK[])")
        results = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r["label"] for r in results], ["spam", "ham"])
        self.assertEqual(results[0]["message"], "uid:1")


if __name__ == "__main__":
    unittest.main()
