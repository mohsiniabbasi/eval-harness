"""
run_eval.py -- run every test case against a system and report what broke.

    python run_eval.py --adapter mock --label baseline
    python run_eval.py --adapter gemini --repeat 3 --label prompt-v2

Reads test cases from a CSV, sends each input to the chosen adapter, grades
the answer, and writes a timestamped JSON result file that compare.py can
diff against a later run.
"""

import argparse
import csv
import datetime
import json
import os
import sys
import time

from adapters import ADAPTERS
from graders import GRADERS

# Windows consoles default to a legacy codepage, which turns a pound sign
# into a question mark. The JSON file is always UTF-8; this makes the
# printed report match it.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))


def percentile(values, fraction):
    """
    Return the value at a given position in a sorted list.

    p50 is the typical case. p95 is the slow tail -- the one users complain
    about. Averages hide the tail, which is why this reports both.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return ordered[index]


def load_cases(path, only_tag=None):
    """Read the test cases CSV into a list of dicts."""
    with open(path, newline="", encoding="utf-8") as handle:
        cases = list(csv.DictReader(handle))

    if only_tag:
        cases = [c for c in cases if c.get("tag") == only_tag]

    for case in cases:
        if case.get("grader") not in GRADERS:
            known = ", ".join(sorted(GRADERS))
            raise SystemExit(
                "Case " + str(case.get("id")) + ": unknown grader "
                + str(case.get("grader")) + ". Known graders: " + known
            )
    return cases


def run_case(case, adapter, repeat):
    """
    Run one test case `repeat` times and grade every attempt.

    Running more than once matters because language models are not
    deterministic. A case that passes 2 times out of 3 is not a passing
    case -- it is a flaky case, and flaky is its own category of broken.
    """
    attempts = []

    for _ in range(repeat):
        started = time.perf_counter()
        try:
            response = adapter(case["input"])
        except Exception as error:
            # One exploding case must never kill the whole run -- an eval
            # that stops at the first error tells you about one bug instead
            # of all of them.
            response = {
                "output": "<crash " + type(error).__name__ + ": " + str(error) + ">",
                "tokens": 0,
            }
        elapsed_ms = (time.perf_counter() - started) * 1000

        grader = GRADERS[case["grader"]]
        passed, reason = grader(response["output"], case["expected"], case)

        attempts.append({
            "output": response["output"],
            "passed": passed,
            "reason": reason,
            "latency_ms": round(elapsed_ms, 2),
            "tokens": response.get("tokens", 0),
        })

    pass_count = sum(1 for a in attempts if a["passed"])

    return {
        "id": case["id"],
        "tag": case.get("tag", ""),
        "input": case["input"],
        "grader": case["grader"],
        "expected": case["expected"],
        "attempts": attempts,
        # A case only counts as passing if it passed EVERY time.
        "passed": pass_count == repeat,
        "flaky": 0 < pass_count < repeat,
        "pass_count": pass_count,
        "runs": repeat,
    }


def summarise(results):
    """Turn per-case results into the numbers that go in the report."""
    latencies = [a["latency_ms"] for r in results for a in r["attempts"]]
    tokens = sum(a["tokens"] for r in results for a in r["attempts"])

    by_tag = {}
    for result in results:
        bucket = by_tag.setdefault(result["tag"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        if result["passed"]:
            bucket["passed"] += 1

    passed = sum(1 for r in results if r["passed"])

    return {
        "cases": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "flaky": sum(1 for r in results if r["flaky"]),
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "by_tag": by_tag,
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "max": round(max(latencies), 2) if latencies else 0.0,
        },
        "total_tokens": tokens,
    }


def print_report(run):
    """Print the human-readable version. The JSON file is the machine version."""
    summary = run["summary"]
    bar = "=" * 66

    print("")
    print(bar)
    print("  EVAL RUN: " + run["label"])
    print("  adapter: " + run["adapter"] + "   cases: " + str(summary["cases"])
          + "   repeats: " + str(run["repeat"]) + "   " + run["timestamp"])
    print(bar)

    rate = summary["pass_rate"] * 100
    print("")
    print("  PASS RATE   {:5.1f}%   ({} passed, {} failed, {} flaky)".format(
        rate, summary["passed"], summary["failed"], summary["flaky"]))

    latency = summary["latency_ms"]
    print("  LATENCY     p50 {:.1f} ms   p95 {:.1f} ms   max {:.1f} ms".format(
        latency["p50"], latency["p95"], latency["max"]))
    print("  TOKENS      " + str(summary["total_tokens"]))

    print("")
    print("  BY TAG")
    for tag, counts in sorted(summary["by_tag"].items()):
        tag_rate = counts["passed"] / counts["total"] * 100
        flag = "  <-- weakest" if tag_rate < 60 else ""
        print("    {:<12} {:>2}/{:<2}  {:5.1f}%{}".format(
            tag, counts["passed"], counts["total"], tag_rate, flag))

    failures = [r for r in run["results"] if not r["passed"]]
    if failures:
        print("")
        print("  FAILURES (" + str(len(failures)) + ")")
        for failure in failures:
            first = failure["attempts"][0]
            shown = failure["input"][:58].replace("\n", " ") or "<empty>"
            print("")
            print("    [" + failure["id"] + "] " + failure["tag"])
            print("      input:  " + shown)
            print("      wanted: " + failure["expected"] + "   (" + failure["grader"] + ")")
            print("      got:    " + str(first["output"])[:58])
            print("      why:    " + first["reason"])

    flaky = [r for r in run["results"] if r["flaky"]]
    if flaky:
        print("")
        print("  FLAKY (" + str(len(flaky)) + ") -- same input, different answers")
        for case in flaky:
            print("    [" + case["id"] + "] passed "
                  + str(case["pass_count"]) + "/" + str(case["runs"]) + " runs")

    print("")
    print(bar)
    print("")


def main():
    parser = argparse.ArgumentParser(description="Run an eval suite against a system.")
    parser.add_argument("--adapter", default="mock", choices=sorted(ADAPTERS),
                        help="which system to test (default: mock, runs offline)")
    parser.add_argument("--cases", default=os.path.join(HERE, "testcases", "moderation.csv"),
                        help="path to the test cases CSV")
    parser.add_argument("--repeat", type=int, default=1,
                        help="run each case N times to detect flakiness")
    parser.add_argument("--label", default="run",
                        help="name for this run, used in the result filename")
    parser.add_argument("--tag", default=None, help="only run cases with this tag")
    parser.add_argument("--out", default=None, help="write results to this path")
    args = parser.parse_args()

    cases = load_cases(args.cases, args.tag)
    if not cases:
        raise SystemExit("No test cases matched.")

    adapter = ADAPTERS[args.adapter]

    print("Running " + str(len(cases)) + " cases against " + args.adapter
          + " (" + str(args.repeat) + " run(s) each)...")

    results = []
    for number, case in enumerate(cases, start=1):
        results.append(run_case(case, adapter, args.repeat))
        print("\r  " + str(number) + "/" + str(len(cases)), end="", flush=True)
    print("")

    run = {
        "schema": 1,
        "label": args.label,
        "adapter": args.adapter,
        "cases_file": os.path.basename(args.cases),
        "repeat": args.repeat,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "summary": summarise(results),
        "results": results,
    }

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = args.out or os.path.join(HERE, "results", args.label + "-" + stamp + ".json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(run, handle, indent=2, ensure_ascii=False)

    print_report(run)
    print("  saved: " + out_path)
    print("")

    # Exit code 1 when anything failed, so this can gate a deploy or a CI job.
    return 0 if run["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
