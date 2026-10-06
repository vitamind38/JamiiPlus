"""Pick the confidence threshold from pilot data, not in advance.

    jamii export-labelled --out /data/labelled.csv
    python ml/scripts/thresholds.py --data /data/labelled.csv --target 0.95

Uses reports where the model made a guess and a person decided the theme. For each
threshold it shows how often reviewers agreed with the model above it, and how much of
the queue it would clear. Set JAMII_CLASSIFY_MIN_CONFIDENCE to the recommended value.
"""

import argparse
from pathlib import Path

from jamii_ml.evaluation import read_labelled


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--target", type=float, default=0.95, help="agreement reviewers must reach")
    p.add_argument("--min-covered", type=int, default=30, help="reports above threshold needed to trust it")
    args = p.parse_args()

    rows = [r for r in read_labelled(args.data, human_only=True) if r.model_theme and r.model_confidence is not None]
    if not rows:
        raise SystemExit(
            "No reviewed reports with a model guess yet. Run assisted mode with thresholds above 1.0 first."
        )
    print(f"{len(rows)} reviewed reports with a model guess\n")
    print(f"{'threshold':>9}{'covered':>9}{'share':>8}{'agreement':>11}")
    best = None
    for step in range(30, 100):
        t = step / 100
        above = [r for r in rows if r.model_confidence >= t]
        if not above:
            break
        agree = sum(r.model_theme == r.label for r in above) / len(above)
        if step % 5 == 0:
            print(f"{t:>9.2f}{len(above):>9}{len(above) / len(rows):>8.0%}{agree:>11.1%}")
        if best is None and agree >= args.target and len(above) >= args.min_covered:
            best = (t, len(above), agree)
    if best:
        print(
            f"\nRecommended: JAMII_CLASSIFY_MIN_CONFIDENCE={best[0]:.2f} ({best[2]:.1%} agreement on {best[1]} reports)"
        )
    else:
        print(
            f"\nNo threshold reaches {args.target:.0%} agreement on {args.min_covered}+ reports. "
            "Keep every report in the review queue."
        )


if __name__ == "__main__":
    main()
