"""Train a theme classifier on human-labelled reports and register it (not active).

    jamii export-labelled --human-only --out /data/labelled.csv      # in the api container
    jamii export-themes --out /data/themes.json
    python ml/scripts/train_classifier.py --data /data/labelled.csv --themes /data/themes.json

Runs on the server. Never copy production reports to a laptop.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from jamii_ml import registry
from jamii_ml.classifiers import KeywordClassifier, normalise
from jamii_ml.evaluation import frozen_test_ids, read_labelled, scores

STATE = registry.registry_path().parent  # the registry, models and held-out ids live together
MIN_TRAIN = 50


def build_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "features",
                FeatureUnion(
                    [
                        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
                        # Character n-grams cope with Sheng, misspellings and mixed Swahili-English.
                        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True)),
                    ]
                ),
            ),
            ("clf", LogisticRegression(max_iter=3000, class_weight="balanced")),
        ]
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--themes", type=Path, required=True, help="JSON from `jamii export-themes`")
    p.add_argument("--test-ids", type=Path, default=STATE / "data" / "test_ids.txt")
    p.add_argument("--models-dir", type=Path, default=STATE / "models")
    p.add_argument("--registry", type=Path, default=registry.registry_path())
    p.add_argument("--version", default=f"tfidf-logreg-{datetime.now(UTC):%Y%m%d}")
    args = p.parse_args()

    rows = read_labelled(args.data, human_only=True)
    test_ids = frozen_test_ids(rows, args.test_ids)
    train = [r for r in rows if r.report_id not in test_ids]
    test = [r for r in rows if r.report_id in test_ids]
    if len(train) < MIN_TRAIN or len({r.label for r in train}) < 2 or not test:
        sys.exit(
            f"Not enough labelled reports yet: {len(train)} to train, {len(test)} to test. "
            f"Keep tagging by hand; the keyword baseline stays active."
        )

    pipeline = build_pipeline()
    pipeline.fit([normalise(r.text) for r in train], [r.label for r in train])
    model_pred = list(pipeline.predict([normalise(r.text) for r in test]))
    themes = json.loads(args.themes.read_text(encoding="utf-8"))
    baseline = KeywordClassifier()
    base_pred = [baseline.predict(r.text, r.language, themes).theme for r in test]
    y = [r.label for r in test]
    model_scores, base_scores = scores(y, model_pred), scores(y, base_pred)

    args.models_dir.mkdir(parents=True, exist_ok=True)
    out = args.models_dir / f"{args.version}.joblib"
    joblib.dump({"pipeline": pipeline, "trained_at": datetime.now(UTC).isoformat()}, out)

    data = registry.load(args.registry)
    data["classifier"]["versions"][args.version] = {
        "kind": "sklearn",
        "path": str(out.relative_to(args.registry.parent)).replace("\\", "/"),
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "train_size": len(train),
        "metrics": {
            **model_scores,
            "baseline_macro_f1": base_scores["macro_f1"],
            "baseline_per_theme_f1": base_scores["per_theme_f1"],
        },
    }
    registry.save(data, args.registry)

    print(f"\n{args.version}: trained on {len(train)}, tested on {len(test)} held-out reports")
    print(f"{'theme':<16}{'support':>8}{'model F1':>10}{'baseline F1':>13}")
    for theme in model_scores["per_theme_f1"]:
        print(
            f"{theme:<16}{model_scores['support'][theme]:>8}{model_scores['per_theme_f1'][theme]:>10.2f}"
            f"{base_scores['per_theme_f1'].get(theme, 0):>13.2f}"
        )
    print(f"{'macro-F1':<16}{'':>8}{model_scores['macro_f1']:>10.2f}{base_scores['macro_f1']:>13.2f}")
    print(f"\nRegistered, not active. To serve it: python ml/scripts/promote.py --version {args.version}")


if __name__ == "__main__":
    main()
