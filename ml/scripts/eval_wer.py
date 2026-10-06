"""Word error rate of model transcripts against reviewers' hand transcripts.

jamii export-transcripts --out /data/transcripts.csv
python ml/scripts/eval_wer.py --data /data/transcripts.csv
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from jamii_ml.evaluation import word_error_rate


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, required=True)
    args = p.parse_args()
    totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    with open(args.data, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            edits, words = word_error_rate(r["human_text"], r["machine_text"])
            t = totals[(r["machine_model_version"], r["language"])]
            t[0] += edits
            t[1] += words
            t[2] += 1
    if not totals:
        raise SystemExit("No corrected transcripts yet.")
    print(f"{'model':<32}{'lang':>5}{'notes':>7}{'WER':>8}")
    for (model, lang), (edits, words, n) in sorted(totals.items()):
        print(f"{model:<32}{lang:>5}{n:>7}{edits / max(words, 1):>8.1%}")


if __name__ == "__main__":
    main()
