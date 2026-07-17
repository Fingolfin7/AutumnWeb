"""Tolerant differ for characterization golden trees.

Usage: python golden_diff.py <old_goldens_dir> <new_goldens_dir> [--tol 0.05]

Compares the raw/ and semantic/ trees of two golden snapshots and classifies
every leaf-level difference:
  - timestamp-floor : ISO datetime where new == old truncated to whole seconds
  - numeric         : float/int delta (reported with magnitude; OK if <= tol)
  - large-numeric   : numeric delta above tol (listed for eyeball review)
  - MISMATCH        : anything else (red flag)
  - only-in-old / only-in-new : file set changes

Exit code 0 if no MISMATCH entries, 1 otherwise. Numeric drift never fails the
run by itself — it is summarized for human review.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?$")


def parse_iso(text):
    if not isinstance(text, str) or not ISO_RE.match(text):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def walk(old, new, path, out):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            if key not in old:
                out.append(("MISMATCH", path + "." + str(key), "<absent>", repr(new[key])))
            elif key not in new:
                out.append(("MISMATCH", path + "." + str(key), repr(old[key]), "<absent>"))
            else:
                walk(old[key], new[key], path + "." + str(key), out)
        return
    if isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            out.append(("MISMATCH", path + ".<len>", str(len(old)), str(len(new))))
            return
        for i, (a, b) in enumerate(zip(old, new)):
            walk(a, b, "%s[%d]" % (path, i), out)
        return
    if old == new:
        return
    if isinstance(old, bool) or isinstance(new, bool):
        out.append(("MISMATCH", path, repr(old), repr(new)))
        return
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        out.append(("numeric", path, old, new))
        return
    old_dt, new_dt = parse_iso(old), parse_iso(new)
    if old_dt and new_dt and old_dt.replace(microsecond=0) == new_dt.replace(microsecond=0) and new_dt.microsecond == 0:
        out.append(("timestamp-floor", path, old, new))
        return
    #

    # body_text of raw goldens is JSON-in-a-string: recurse structurally.
    if isinstance(old, str) and isinstance(new, str):
        try:
            old_j, new_j = json.loads(old), json.loads(new)
        except (ValueError, TypeError):
            out.append(("MISMATCH", path, old[:120], new[:120]))
            return
        walk(old_j, new_j, path + ".<body>", out)
        return
    out.append(("MISMATCH", path, repr(old)[:120], repr(new)[:120]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--tol", type=float, default=0.05)
    args = ap.parse_args()

    old_root, new_root = Path(args.old), Path(args.new)
    old_files = {p.relative_to(old_root) for p in old_root.rglob("*.json")}
    new_files = {p.relative_to(new_root) for p in new_root.rglob("*.json")}

    mismatches = []
    floors = 0
    numeric = []
    for rel in sorted(old_files - new_files):
        mismatches.append(("only-in-old", str(rel), "", ""))
    for rel in sorted(new_files - old_files):
        print("note: only-in-new %s (new coverage)" % rel)
    for rel in sorted(old_files & new_files):
        if rel.name == "fingerprint.json":
            continue
        old = json.loads((old_root / rel).read_text(encoding="utf-8"))
        new = json.loads((new_root / rel).read_text(encoding="utf-8"))
        diffs = []
        walk(old, new, str(rel), diffs)
        for kind, path, a, b in diffs:
            if kind == "timestamp-floor":
                floors += 1
            elif kind == "numeric":
                numeric.append((abs(a - b), path, a, b))
            else:
                mismatches.append((kind, path, a, b))

    print("\n=== summary ===")
    print("timestamp-floor diffs: %d" % floors)
    print("numeric diffs: %d" % len(numeric))
    if numeric:
        numeric.sort(reverse=True)
        print("  max |delta| = %.6f" % numeric[0][0])
        over = [n for n in numeric if n[0] > args.tol]
        print("  over tol (%.3f): %d" % (args.tol, len(over)))
        for delta, path, a, b in over[:40]:
            print("    %.6f  %s  %s -> %s" % (delta, path, a, b))
        if len(over) > 40:
            print("    ... %d more" % (len(over) - 40))
    print("MISMATCH entries: %d" % len(mismatches))
    for kind, path, a, b in mismatches[:60]:
        print("  [%s] %s\n      old=%s\n      new=%s" % (kind, path, a, b))
    if len(mismatches) > 60:
        print("  ... %d more" % (len(mismatches) - 60))
    sys.exit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
