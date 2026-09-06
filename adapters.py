"""
adapters.py -- how the harness talks to the system being tested.

An "adapter" is just a function that takes one input string and returns
a dict:  {"output": "...", "tokens": 123}

Everything else in the harness only ever sees that dict. That means the
grading, reporting and regression code never has to know whether the
answer came from a local fake, from Gemini, or from a live endpoint.
That separation is the whole point: swap the adapter, keep the tests.
"""

import json
import os
import re
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# 1. MOCK -- runs offline, no API key, no cost.
# ---------------------------------------------------------------------------

# A deliberately naive keyword classifier. It is SUPPOSED to be imperfect:
# it reads keywords and ignores context, so it gets sarcasm and negation
# wrong. That gives the harness real failures to find on the very first run.
_HIDE_WORDS = ["idiot", "scam", "stupid", "garbage", "rubbish", "liar", "clown"]
_ESCALATE_WORDS = ["sue", "lawyer", "solicitor", "ombudsman", "fca", "trading standards"]


def mock_moderation(text):
    """Classify a comment as keep / hide / escalate using dumb keyword matching."""
    lowered = text.lower()

    for word in _ESCALATE_WORDS:
        if word in lowered:
            return {"output": "escalate", "tokens": len(text) // 4}

    for word in _HIDE_WORDS:
        if word in lowered:
            return {"output": "hide", "tokens": len(text) // 4}

    return {"output": "keep", "tokens": len(text) // 4}


# ---------------------------------------------------------------------------
# 1b. MOCK v2 -- a plausible "fix" for the v1 failures.
# ---------------------------------------------------------------------------

# v1 failed on spam, on a regulator threat, and on negated keywords like
# "worried this was a scam but they were brilliant". So v2 adds spam phrases,
# adds "regulator", and puts in a positive-sentiment override: if the comment
# contains an obviously positive word, keep it.
#
# That override is the kind of fix that looks obviously right and is not.
# Run compare.py to see what it costs.
_POSITIVE_WORDS = ["brilliant", "great", "thanks", "fine", "recommended", "wonderful"]
_SPAM_PHRASES = ["dm me", "link in bio", "working from home", "signals channel"]
_ESCALATE_WORDS_V2 = _ESCALATE_WORDS + ["regulator"]


def mock_moderation_v2(text):
    """Second iteration of the keyword classifier."""
    lowered = text.lower()
    tokens = len(text) // 4

    # New in v2: positive sentiment overrides everything else.
    for word in _POSITIVE_WORDS:
        if word in lowered:
            return {"output": "keep", "tokens": tokens}

    for word in _ESCALATE_WORDS_V2:
        if word in lowered:
            return {"output": "escalate", "tokens": tokens}

    for phrase in _SPAM_PHRASES:
        if phrase in lowered:
            return {"output": "hide", "tokens": tokens}

    for word in _HIDE_WORDS:
        if word in lowered:
            return {"output": "hide", "tokens": tokens}

    return {"output": "keep", "tokens": tokens}


# ---------------------------------------------------------------------------
# 2. GEMINI -- real LLM call. Needs GEMINI_API_KEY in the environment.
# ---------------------------------------------------------------------------

# Kept on a -lite model on purpose: this harness may run hundreds of calls
# and the free tier has quotas. Cheap model, high volume.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")

SYSTEM_PROMPT = """You are a comment moderator for a UK business page.
Classify the comment into exactly one of: keep, hide, escalate.

keep     = normal comment, including negative but fair criticism
hide     = abuse, insults, spam, or defamation
escalate = threatens legal or regulatory action, or alleges serious harm

Reply with the single word only. No punctuation, no explanation."""


def gemini(text):
    """Send one comment to Gemini and return its classification."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Use --adapter mock to run offline.")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": text}]}],
        # temperature 0 makes the model as repeatable as it can be. It is
        # still not guaranteed identical every time -- that is exactly why
        # the harness has a --repeat flag to measure flakiness.
        "generationConfig": {"temperature": 0, "maxOutputTokens": 20},
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:200]
        return {"output": f"<error {error.code}: {detail}>", "tokens": 0}
    except Exception as error:
        return {"output": f"<error {type(error).__name__}: {error}>", "tokens": 0}

    # Pull the text out of Gemini's response shape, defensively -- a blocked
    # or empty response has no "candidates" key at all, and crashing here
    # would lose the whole run.
    try:
        answer = body["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        answer = "<no answer returned>"

    used = body.get("usageMetadata", {}).get("totalTokenCount", 0)
    return {"output": answer.lower().strip(". \n"), "tokens": used}


# ---------------------------------------------------------------------------
# 3. HTTP -- point at your own deployed service.
# ---------------------------------------------------------------------------

def http_endpoint(text):
    """
    POST the input to your own service and read one field back.

    Configure with environment variables so no URL is hard-coded here:
        EVAL_ENDPOINT_URL    e.g. https://moderation.pivotbureau.com/api/classify
        EVAL_REQUEST_FIELD   name of the field to send   (default: "text")
        EVAL_RESPONSE_FIELD  name of the field to read    (default: "label")
    """
    url = os.environ.get("EVAL_ENDPOINT_URL")
    if not url:
        raise RuntimeError("EVAL_ENDPOINT_URL is not set.")

    request_field = os.environ.get("EVAL_REQUEST_FIELD", "text")
    response_field = os.environ.get("EVAL_RESPONSE_FIELD", "label")

    request = urllib.request.Request(
        url,
        data=json.dumps({request_field: text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        return {"output": f"<error {type(error).__name__}: {error}>", "tokens": 0}

    return {"output": str(body.get(response_field, body)).lower().strip(), "tokens": 0}


# The runner looks the adapter up by name in this dict.
ADAPTERS = {
    "mock": mock_moderation,
    "mock_v2": mock_moderation_v2,
    "gemini": gemini,
    "http": http_endpoint,
}
