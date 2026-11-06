# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""A deterministic filter for what an agent writes in the memory: no credential, ever.

One function, used by every write of a text an agent gives (a note, a lesson, a note of a task,
the summary of a document): it returns why the text cannot be stored, or None. A key, a token
or a password in the memory would reach every session that reads the record; a refusal says
what it saw, so the agent rewrites. The converted text of a document is not filtered here: a
document is a source, kept as it is, and its ingestion decides what to keep.
"""
import re

PATTERNS = (
    (re.compile(r"(?i)\w*(?:api[_-]?key|token|secret|password|passwd)\w*\s*[:=]\s*\S{6,}"), "a named key, token or password"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), "a bearer token"),
    (re.compile(r"\b(?:sk|ghp|gho|ghs|github_pat|xox[abprs])[-_][A-Za-z0-9_\-]{12,}"), "an API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "a JWT"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\b[0-9a-f]{48,}\b"), "a long hexadecimal secret"),
)


def credential_reason(text):
    """What in the text looks like a credential, or None when nothing does."""
    for pattern, what in PATTERNS:
        if pattern.search(text or ""):
            return what
    return None


def check_no_credential(env, *texts):
    """Raise a UserError when one of the texts holds what looks like a credential."""
    from odoo.exceptions import UserError  # noqa: PLC0415 - a helper of the models, imported where it runs
    for text in texts:
        reason = credential_reason(text if isinstance(text, str) else " ".join(text or []) if text else "")
        if reason:
            raise UserError(env._("The text holds what looks like %s: a credential never goes in the memory. "
                                  "Remove it and write again.", reason))
