"""
fix_duplicate_filenames.py — Helper to identify (and optionally clean) the messy duplicate files
that have crept into the repo (e.g. "requirements (4).txt", "safe_code_executor (1).py", etc).

These filenames with spaces and parentheses are the #1 reason `pip install ...` commands fail
with parser errors.

Run:
    python fix_duplicate_filenames.py          # just report
    python fix_duplicate_filenames.py --delete  # DANGEROUS: actually delete duplicates (review first!)
"""

import os
from pathlib import Path
import argparse
import re

PROJECT_ROOT = Path(__file__).parent.resolve()

# Pattern for the problematic copies
DUP_PATTERN = re.compile(r'^(?P<base>.+?)(?:\s+\(\d+\)|\s+-\s+Copy|\s+\(Copy\))\.(?P<ext>.+)$', re.IGNORECASE)

SUSPICIOUS_SUFFIXES = [
    " (1)", " (2)", " (3)", " (4)", " (5)",
    " - Copy", " (Copy)", " (copy)"
]

def find_duplicates():
    dups = []
    for f in PROJECT_ROOT.rglob("*"):
        if not f.is_file():
            continue
        name = f.name
        if any(s in name for s in SUSPICIOUS_SUFFIXES) or DUP_PATTERN.match(name):
            # Skip things inside venv, __pycache__, .git, chroma_db etc.
            if any(part in f.parts for part in (".venv", "venv", "__pycache__", ".git", "chroma_db", "node_modules")):
                continue
            dups.append(f)
    return sorted(dups)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true", help="Actually delete the duplicate files (USE WITH CAUTION)")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()

    dups = find_duplicates()

    if not dups:
        print("✅ No obviously duplicated files with (1), (2), ' - Copy' etc. found in project root tree.")
        return

    print(f"⚠️  Found {len(dups)} suspicious duplicate / copy files:\n")
    for p in dups:
        print(f"   {p.relative_to(PROJECT_ROOT)}")

    print("\nRecommended action:")
    print("  1. Review the list above.")
    print("  2. Manually delete the ones you don't need (keep the clean versions without numbers).")
    print("  3. After cleanup, run:  git status   (if using git)")

    if args.delete:
        print("\n🚨 --delete was passed. Deleting now...")
        for p in dups:
            try:
                p.unlink()
                print(f"   Deleted: {p.name}")
            except Exception as e:
                print(f"   ERROR deleting {p.name}: {e}")
        print("Done.")
    else:
        print("\nRun with --delete ONLY after you have reviewed the list and are sure.")

if __name__ == "__main__":
    main()