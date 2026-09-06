"""
compare.py -- diff two eval runs and fail loudly on regressions.

    python compare.py                              (compares the two newest runs)
    python compare.py results/a.json results/b.json

This is the part that makes the harness worth having. A single pass rate
tells you almost nothing on its own. What you actually need to know before
shipping a prompt change is: "which cases used to work and now don't?"

That is a regression, and it is the one thing a top-line percentage will
happily hide -- you can fix four cases, break four others, and the headline
number will not move at all.

Exit code is 1 if there are any regressions, so this can gate a deploy.
"""

import glob
import json
import os
import sys

# Windows consoles default to a legacy codepage, which turns a pound sign
# into a question mark. The JSON file is always UTF-8; this makes the
# printed report match it.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))


def load_run(path):
    """Read one saved run, with a clear error if it is not a run file."""
    with open(path, encoding="utf-8") as handle:
        run = json.load(handle)
    if "results" not in run:
        raise SystemExit(path + " does not look like an eval run file.")
    return run


def newest_two():
    """Find the two most recently written result files."""
    files = sorted(
        glob.glob(os.path.join(HERE, "results", "*.json")),
        key=os.path.getmtime,
    )
    if len(files) < 2:
        raise SystemExit(
            "Need at least two runs in results/ to compare. "
            "Run run_eval.py twice first."
        )
    return files[-2], files[-1]


def index_by_id(run):
    """Turn the results list into a lookup of case id -> result."""
    return {result["id"]: result for result in run["results"]}


def main():
    if len(sys.argv) == 3:
        before_path, after_path = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 1:
        before_path, after_path = newest_two()
    else:
        raise SystemExit("Usage: python compare.py [before.json after.json]")

    before, after = load_run(before_path), load_run(after_path)
    before_cases, after_cases = index_by_id(before), index_by_id(after)

    shared = set(before_cases) & set(after_cases)

    regressions = sorted(
        case_id for case_id in shared
        if before_cases[case_id]["passed"] and not after_cases[case_id]["passed"]
    )
    fixes = sorted(
        case_id for case_id in shared
        if not before_cases[case_id]["passed"] and after_cases[case_id]["passed"]
    )
    still_failing = sorted(
        case_id for case_id in shared
        if not before_cases[case_id]["passed"] and not after_cases[case_id]["passed"]
    )

    added = sorted(set(after_cases) - set(before_cases))
    removed = sorted(set(before_cases) - set(after_cases))

    bar = "=" * 66
    print("")
    print(bar)
    print("  COMPARE")
    print("    before: " + before["label"] + "  (" + os.path.basename(before_path) + ")")
    print("    after:  " + after["label"] + "  (" + os.path.basename(after_path) + ")")
    print(bar)

    before_rate = before["summary"]["pass_rate"] * 100
    after_rate = after["summary"]["pass_rate"] * 100
    delta = after_rate - before_rate
    arrow = "+" if delta >= 0 else ""

    print("")
    print("  PASS RATE   {:.1f}%  ->  {:.1f}%   ({}{:.1f} points)".format(
        before_rate, after_rate, arrow, delta))

    before_p95 = before["summary"]["latency_ms"]["p95"]
    after_p95 = after["summary"]["latency_ms"]["p95"]
    print("  LATENCY p95 {:.1f} ms  ->  {:.1f} ms".format(before_p95, after_p95))

    if regressions:
        print("")
        print("  *** REGRESSIONS (" + str(len(regressions)) + ") -- these used to pass ***")
        for case_id in regressions:
            case = after_cases[case_id]
            print("")
            print("    [" + case_id + "] " + case["tag"])
            print("      input:  " + (case["input"][:58] or "<empty>"))
            print("      wanted: " + case["expected"])
            print("      got:    " + str(case["attempts"][0]["output"])[:58])
    else:
        print("")
        print("  REGRESSIONS  none")

    if fixes:
        print("")
        print("  FIXED (" + str(len(fixes)) + ")")
        for case_id in fixes:
            print("    [" + case_id + "] " + after_cases[case_id]["tag"])

    if still_failing:
        print("")
        print("  STILL FAILING (" + str(len(still_failing)) + ")")
        print("    " + ", ".join(still_failing))

    if added:
        print("")
        print("  NEW CASES (" + str(len(added)) + "): " + ", ".join(added))
    if removed:
        print("")
        print("  REMOVED CASES (" + str(len(removed)) + "): " + ", ".join(removed))

    print("")
    print(bar)
    if regressions:
        print("  VERDICT: DO NOT SHIP -- " + str(len(regressions)) + " regression(s)")
    elif delta > 0:
        print("  VERDICT: improvement, no regressions")
    else:
        print("  VERDICT: no regressions")
    print(bar)
    print("")

    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
