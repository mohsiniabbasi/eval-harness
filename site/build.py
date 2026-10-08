"""
build.py -- turn two saved eval runs into one static results page.

    python site/build.py                              (uses the two runs below)
    python site/build.py results/a.json results/b.json

Writes site/index.html. No server, no JavaScript, no dependencies: the page
is plain HTML so it can be dropped on any web host.

Every number on the page is read from the run files. Nothing is typed in by
hand, so the page cannot drift from what the harness actually produced.
"""

import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The two runs behind the write-up: the baseline and the "fix" that
# raised the pass rate while breaking two cases.
DEFAULT_BEFORE = os.path.join(ROOT, "results", "v1-baseline-20260830-125809.json")
DEFAULT_AFTER = os.path.join(
    ROOT, "results", "v2-positive-override-20260830-125815.json"
)


def load_run(path):
    """Read one saved run, with a clear error if it is not a run file."""
    with open(path, encoding="utf-8") as handle:
        run = json.load(handle)
    if "results" not in run:
        raise SystemExit(path + " does not look like an eval run file.")
    return run


def esc(value):
    """Escape text for HTML. Test inputs are untrusted by design."""
    return html.escape(str(value), quote=True)


def last_output(result):
    """The answer the classifier gave on its final attempt."""
    return result["attempts"][-1]["output"]


def percent(rate):
    return "{:.1f}%".format(rate * 100)


def change_of(before, after):
    """Classify one case by what happened between the two runs."""
    if before["passed"] and not after["passed"]:
        return "regression"
    if not before["passed"] and after["passed"]:
        return "fixed"
    if not before["passed"] and not after["passed"]:
        return "still failing"
    return "unchanged"


def answer_cell(result):
    mark = "pass" if result["passed"] else "fail"
    return '<td class="{}">{}</td>'.format(mark, esc(last_output(result)))


def case_row(before, after):
    change = change_of(before, after)
    css = change.replace(" ", "-")
    return (
        '<tr class="{css}">'
        "<td>{id}</td><td>{tag}</td><td>{text}</td><td>{want}</td>"
        "{v1}{v2}"
        '<td><span class="pill {css}">{change}</span></td>'
        "</tr>"
    ).format(
        css=css,
        id=esc(after["id"]),
        tag=esc(after["tag"]),
        text=esc(after["input"]),
        want=esc(after["expected"]),
        v1=answer_cell(before),
        v2=answer_cell(after),
        change=change,
    )


def regression_card(before, after):
    return (
        '<div class="card bad">'
        '<p class="label">{id} &middot; {tag}</p>'
        '<p class="quote">&ldquo;{text}&rdquo;</p>'
        "<p>Right answer: <b>{want}</b>. Version 1 said <b>{v1}</b>. "
        "Version 2 said <b>{v2}</b>.</p>"
        "</div>"
    ).format(
        id=esc(after["id"]),
        tag=esc(after["tag"]),
        text=esc(after["input"]),
        want=esc(after["expected"]),
        v1=esc(last_output(before)),
        v2=esc(last_output(after)),
    )


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>A higher score that made things worse</title>
<meta name="description" content="A small test harness for a comment-moderation classifier. One change raised the pass rate from {before_rate} to {after_rate} and broke {n_regressions} cases that used to work." />
<style>
  :root {{
    --bg: #f6f7f9; --card: #ffffff; --ink: #1a1d21; --muted: #6b7280;
    --line: #e5e7eb; --accent: #0f6e56; --accent-soft: #e1f5ee;
    --bad: #a3271f; --bad-soft: #fdecea;
    --warn: #9a5b00; --warn-soft: #fdf1df;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0e1113; --card: #171a1d; --ink: #e8eaed; --muted: #9aa1a9;
      --line: #2a2f34; --accent: #5dcaa5; --accent-soft: #10352c;
      --bad: #f08a80; --bad-soft: #3a1815;
      --warn: #e0a458; --warn-soft: #2a2113;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex; justify-content: center; padding: 32px 16px;
  }}
  .wrap {{ width: 100%; max-width: 860px; }}
  h1 {{ font-size: 26px; font-weight: 600; line-height: 1.25; margin: 0 0 6px; }}
  h2 {{ font-size: 18px; font-weight: 600; margin: 32px 0 10px; }}
  p {{ margin: 0 0 12px; }}
  .sub {{ color: var(--muted); margin: 0 0 20px; }}
  .card {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 12px; padding: 18px 20px; margin-bottom: 14px;
  }}
  .card.bad {{ background: var(--bad-soft); border-color: var(--bad); }}
  .card.note {{ background: var(--warn-soft); border-color: var(--warn); }}
  .card p:last-child {{ margin-bottom: 0; }}
  .label {{
    font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
    color: var(--muted); margin: 0 0 6px;
  }}
  .scores {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }}
  .scores .card {{ margin-bottom: 0; }}
  .big {{ font-size: 34px; font-weight: 600; line-height: 1.1; margin: 0 0 4px; }}
  .verdict .big {{ color: var(--bad); font-size: 26px; padding-top: 6px; }}
  .small {{ font-size: 14px; color: var(--muted); margin: 0; }}
  .quote {{ font-size: 18px; margin: 0 0 8px; }}
  .scroll {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{
    text-align: left; padding: 8px 10px; vertical-align: top;
    border-bottom: 1px solid var(--line);
  }}
  th {{
    font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
    color: var(--muted); font-weight: 600; white-space: nowrap;
  }}
  td.pass {{ color: var(--accent); }}
  td.fail {{ color: var(--bad); font-weight: 600; }}
  tr.regression {{ background: var(--bad-soft); }}
  .pill {{
    font-size: 12px; padding: 3px 9px; border-radius: 999px;
    white-space: nowrap; border: 1px solid var(--line); color: var(--muted);
  }}
  .pill.regression {{ background: var(--bad); border-color: var(--bad); color: #fff; }}
  .pill.fixed {{ background: var(--accent-soft); border-color: var(--accent-soft); color: var(--accent); }}
  .pill.still-failing {{ background: var(--warn-soft); border-color: var(--warn-soft); color: var(--warn); }}
  pre {{
    background: var(--card); border: 1px solid var(--line); border-radius: 8px;
    padding: 14px 16px; overflow-x: auto; font-size: 14px; margin: 0 0 12px;
  }}
  a {{ color: var(--accent); }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 36px; }}
  @media (max-width: 640px) {{
    .scores {{ grid-template-columns: 1fr; }}
    h1 {{ font-size: 22px; }}
  }}
</style>
</head>
<body>
<div class="wrap">

<h1>A higher score that made things worse</h1>
<p class="sub">{n_cases} test comments, two versions of a comment-moderation classifier, and the comparison that stopped the second one going out.</p>

<div class="scores">
  <div class="card">
    <p class="label">Version 1</p>
    <p class="big">{before_rate}</p>
    <p class="small">{before_passed} of {n_cases} correct</p>
  </div>
  <div class="card">
    <p class="label">Version 2, the &ldquo;fix&rdquo;</p>
    <p class="big">{after_rate}</p>
    <p class="small">{after_passed} of {n_cases} correct</p>
  </div>
  <div class="card bad verdict">
    <p class="label">Comparison result</p>
    <p class="big">DO NOT SHIP</p>
    <p class="small">{n_fixed} fixed, {n_regressions} broken</p>
  </div>
</div>

<h2>What happened</h2>
<p>Version 1 missed spam and some legal threats. I added a few rules to catch them, plus one that keeps any comment containing a clearly positive word. The pass rate went up by {gain} points, which looks like a good change.</p>
<p>The case-by-case comparison showed {n_regressions} comments that version 1 handled correctly and version 2 got wrong. Both are sarcastic abuse. The new positive-word rule read them as praise.</p>

{regression_cards}

<p>A moderation tool that lets abuse through is worse at its one job, whatever the score says. So the change was not shipped. The comparison script exits with an error when it finds a case like this, so it can block a release without anyone having to read the report.</p>

<div class="card note">
  <p class="label">What this is and isn't</p>
  <p>The two versions tested here are simple rule-based classifiers written to stand in for a moderation tool. They are not a live AI model. The point of the project is the test method. The same {n_cases} tests can be pointed at a real model by swapping one adapter. It is a small test set, not a production evaluation system.</p>
</div>

<h2>All {n_cases} cases</h2>
<div class="card scroll">
<table>
<thead>
<tr><th>ID</th><th>Type</th><th>Comment</th><th>Right answer</th><th>Version 1</th><th>Version 2</th><th>Change</th></tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<p class="small">{n_still} cases fail in both versions. They are listed, not hidden.</p>

<h2>Run it yourself</h2>
<p>Python 3, standard library only. No install and no API key.</p>
<pre>python run_eval.py --adapter mock --label baseline
python run_eval.py --adapter mock_v2 --label experiment
python compare.py</pre>
<p>Code: <a href="https://github.com/mohsiniabbasi/eval-harness">github.com/mohsiniabbasi/eval-harness</a></p>

<footer>
  Built by Mohsan Abasi &middot; <a href="https://pivotbureau.com">pivotbureau.com</a><br>
  Page generated from the saved run files <code>{before_file}</code> and <code>{after_file}</code>.
</footer>

</div>
</body>
</html>
"""


def main():
    if len(sys.argv) == 3:
        before_path, after_path = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 1:
        before_path, after_path = DEFAULT_BEFORE, DEFAULT_AFTER
    else:
        raise SystemExit("Usage: python site/build.py [before.json after.json]")

    before, after = load_run(before_path), load_run(after_path)
    before_cases = {result["id"]: result for result in before["results"]}

    pairs = [
        (before_cases[result["id"]], result)
        for result in after["results"]
        if result["id"] in before_cases
    ]
    changes = [change_of(old, new) for old, new in pairs]
    regressions = [pair for pair in pairs if change_of(*pair) == "regression"]

    gain = (after["summary"]["pass_rate"] - before["summary"]["pass_rate"]) * 100

    page = PAGE.format(
        n_cases=after["summary"]["cases"],
        before_rate=percent(before["summary"]["pass_rate"]),
        after_rate=percent(after["summary"]["pass_rate"]),
        before_passed=before["summary"]["passed"],
        after_passed=after["summary"]["passed"],
        n_fixed=changes.count("fixed"),
        n_regressions=len(regressions),
        n_still=changes.count("still failing"),
        gain="{:.1f}".format(gain),
        regression_cards="\n".join(regression_card(*pair) for pair in regressions),
        rows="\n".join(case_row(*pair) for pair in pairs),
        before_file=esc(os.path.basename(before_path)),
        after_file=esc(os.path.basename(after_path)),
    )

    out_path = os.path.join(HERE, "index.html")
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(page)
    print("Wrote " + out_path)


if __name__ == "__main__":
    main()
