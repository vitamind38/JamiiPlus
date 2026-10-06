"""Fail if a tracked file looks like it holds real phone numbers, ID numbers, secrets or data dumps.

Synthetic numbers used in tests and seeds are allowed when they sit in the reserved ranges
+2547000000xx, +2547100000xx, +2547110xxxxx and +2547220xxxxx.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHONE = re.compile(r"(?<!\d)(?:\+?254|0)(?:7|1)\d{8}(?!\d)")
SYNTHETIC = re.compile(
    r"^(?:\+?254|0)(?:7000000\d\d|7100000\d\d|7110\d{5}|7220\d{5}|712345678|112345678|799999999|"
    r"799000111|711XXXYYY)$"
)
SECRET = re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{24,}")
BANNED_FILES = re.compile(r"(^|/)(\.env|.*\.dump(\.age)?|.*\.sql\.gz|.*\.csv|.*\.m4a|.*\.wav|.*\.amr|.*\.db)$")
ALLOWED_FILES = {"infra/.env.example"}
SKIP_SUFFIXES = {".png", ".jpg", ".ico", ".lock", ".jar", ".ttf", ".woff2"}


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def main() -> int:
    problems = []
    for rel in tracked():
        if rel in ALLOWED_FILES:
            continue
        if BANNED_FILES.search(rel):
            problems.append(f"{rel}: this kind of file must not be committed (env, dumps, audio, data)")
            continue
        path = ROOT / rel
        if path.suffix in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for m in PHONE.finditer(line.replace(" ", "")):
                if not SYNTHETIC.match(m.group().lstrip("+")) and not SYNTHETIC.match(m.group()):
                    problems.append(f"{rel}:{n}: looks like a real phone number")
            if SECRET.search(line) and "example" not in line.lower() and "CHANGE_ME" not in line:
                problems.append(f"{rel}:{n}: looks like a secret")
    for p in problems:
        print(p)
    if problems:
        print(f"\n{len(problems)} problem(s). Use synthetic data; keep secrets in the server's environment.")
        return 1
    print("No personal data or secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
