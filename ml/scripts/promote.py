"""Make a registered model the active one, but only if it passes its gate. Or roll back.

    python ml/scripts/promote.py --version tfidf-logreg-20270115
    python ml/scripts/promote.py --task transcriber --version whisper-small-sw-2027-01
    python ml/scripts/promote.py --task classifier --rollback

Classifier gate: macro-F1 beats the keyword baseline by a margin and clears a floor, and
no theme with enough test reports falls below a per-theme floor (so rare themes are not
hidden by a good average). Transcriber gate: word error rate at or below a ceiling.
Then restart the model service. Reviewer agreement is the second half of the gate: check
the weekly re-check rate on the dashboard before lowering any confidence threshold.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from jamii_ml import registry


def check_classifier(m: dict, args) -> list[str]:
    problems = []
    if not m:
        return ["no metrics recorded; train it with train_classifier.py"]
    if m["macro_f1"] < m.get("baseline_macro_f1", 0) + args.margin:
        problems.append(
            f"macro-F1 {m['macro_f1']:.2f} does not beat the keyword baseline "
            f"{m.get('baseline_macro_f1', 0):.2f} by {args.margin}"
        )
    if m["macro_f1"] < args.min_macro_f1:
        problems.append(f"macro-F1 {m['macro_f1']:.2f} is below the floor {args.min_macro_f1}")
    for theme, f1 in m.get("per_theme_f1", {}).items():
        if m.get("support", {}).get(theme, 0) >= args.min_support and f1 < args.min_theme_f1:
            problems.append(f"theme {theme}: F1 {f1:.2f} below {args.min_theme_f1}")
    return problems


def check_transcriber(m: dict, args) -> list[str]:
    wer = m.get("wer_sw", m.get("wer"))
    if wer is None:
        return ["no word error rate recorded; measure it with eval_wer.py and add metrics.wer_sw"]
    return [] if wer <= args.max_wer else [f"WER {wer:.2f} above ceiling {args.max_wer}"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", default="classifier", choices=registry.TASKS)
    p.add_argument("--version")
    p.add_argument("--rollback", action="store_true")
    p.add_argument("--registry", type=Path, default=registry.registry_path())
    p.add_argument("--margin", type=float, default=0.02)
    p.add_argument("--min-macro-f1", type=float, default=0.60)
    p.add_argument("--min-theme-f1", type=float, default=0.40)
    p.add_argument("--min-support", type=int, default=5)
    p.add_argument("--max-wer", type=float, default=0.35)
    args = p.parse_args()

    data = registry.load(args.registry)
    task = data[args.task]
    if args.rollback:
        previous = task.get("previous_active")
        if not previous:
            sys.exit("Nothing to roll back to.")
        task["active"], task["previous_active"] = previous, task.get("active")
        registry.save(data, args.registry)
        print(f"{args.task}: rolled back to {previous}. Restart the model service.")
        return
    if not args.version or args.version not in task["versions"]:
        sys.exit(f"Unknown version. Registered: {', '.join(task['versions']) or 'none'}")
    entry = task["versions"][args.version]
    if entry.get("kind") != "keyword":
        checker = check_classifier if args.task == "classifier" else check_transcriber
        problems = checker(entry.get("metrics") or {}, args) if args.task != "ner" else []
        if problems:
            print(f"Not promoted: {args.version}")
            for line in problems:
                print("  -", line)
            sys.exit(1)
    task["previous_active"] = task.get("active")
    task["active"] = args.version
    entry["promoted_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    registry.save(data, args.registry)
    print(f"{args.task}: {args.version} is now active (was {task['previous_active']}). Restart the model service.")


if __name__ == "__main__":
    main()
