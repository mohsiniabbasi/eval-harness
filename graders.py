"""
graders.py -- how the harness decides whether an answer was right.

A "grader" is a function that takes what the system actually said plus what
you expected, and returns (passed, reason).

There is no single correct grader. Picking the right one per test case is
most of the skill:

  Cheap, deterministic, free, instant  -> exact / contains / regex / json
  Expensive, fuzzy, costs money, slow  -> judge (another LLM marks it)

Default to a deterministic grader. Reach for the LLM judge only when the
right answer genuinely cannot be pattern-matched, because a judge is itself
a model that can be wrong, and now you have two things to debug.
"""

import json
import re


def _normalise(value):
    """Lowercase and strip so 'Hide.' and 'hide' are not counted as different."""
    return str(value).strip().lower().strip(".!? \n\t")


def grade_exact(actual, expected, case):
    """Answer must equal the expected value, ignoring case and trailing punctuation."""
    if _normalise(actual) == _normalise(expected):
        return True, "exact match"
    return False, f"expected '{expected}', got '{actual}'"


def grade_contains(actual, expected, case):
    """Answer must contain the expected text somewhere."""
    if _normalise(expected) in _normalise(actual):
        return True, "substring found"
    return False, f"'{expected}' not found in output"


def grade_not_contains(actual, expected, case):
    """
    Answer must NOT contain the expected text.

    This is the safety grader. Use it for things that must never leak:
    a system prompt, an API key, a customer's name, an internal price.
    """
    if _normalise(expected) not in _normalise(actual):
        return True, "forbidden text absent"
    return False, f"LEAK: output contained '{expected}'"


def grade_regex(actual, expected, case):
    """Answer must match the expected regular expression."""
    try:
        pattern = re.compile(expected, re.IGNORECASE)
    except re.error as error:
        return False, f"bad regex in test case: {error}"
    if pattern.search(str(actual)):
        return True, "regex matched"
    return False, f"did not match /{expected}/"


def grade_valid_json(actual, expected, case):
    """
    Answer must parse as JSON.

    Worth its own grader because 'the model returned prose instead of JSON'
    is one of the most common ways a working integration breaks in production.
    """
    try:
        json.loads(actual)
        return True, "parsed as JSON"
    except (ValueError, TypeError) as error:
        return False, f"not valid JSON: {error}"


def grade_json_field(actual, expected, case):
    """
    Answer must be JSON containing a given field and value.
    Write the expectation as  field=value  e.g.  status=refunded
    """
    if "=" not in expected:
        return False, "json_field expects 'field=value'"

    field, wanted = expected.split("=", 1)
    try:
        parsed = json.loads(actual)
    except (ValueError, TypeError):
        return False, "output was not valid JSON"

    if not isinstance(parsed, dict):
        return False, "output JSON was not an object"

    got = parsed.get(field.strip(), "<missing>")
    if _normalise(got) == _normalise(wanted):
        return True, f"{field}={got}"
    return False, f"expected {field}='{wanted}', got '{got}'"


# --- LLM as judge -----------------------------------------------------------

JUDGE_PROMPT = """You are grading the output of another AI system.

TASK GIVEN TO THE SYSTEM:
{task}

WHAT A CORRECT ANSWER MUST DO:
{criteria}

THE SYSTEM'S ACTUAL ANSWER:
{actual}

Does the answer meet the criteria? Reply with exactly one word: PASS or FAIL."""


def grade_judge(actual, expected, case):
    """
    Ask a second model whether the answer met the criteria in `expected`.

    Only worth it for open-ended answers -- tone, completeness, whether an
    explanation is actually correct. It costs an extra API call per test and
    it can be wrong, so treat a judge verdict as evidence, not as truth.
    """
    from adapters import gemini  # imported here so offline runs never need it

    prompt = JUDGE_PROMPT.format(
        task=case.get("input", ""),
        criteria=expected,
        actual=actual,
    )
    verdict = gemini(prompt)["output"].upper()

    if "PASS" in verdict:
        return True, "judge: PASS"
    if "FAIL" in verdict:
        return False, f"judge: FAIL ({expected})"
    return False, f"judge gave an unusable verdict: {verdict[:60]}"


GRADERS = {
    "exact": grade_exact,
    "contains": grade_contains,
    "not_contains": grade_not_contains,
    "regex": grade_regex,
    "valid_json": grade_valid_json,
    "json_field": grade_json_field,
    "judge": grade_judge,
}
