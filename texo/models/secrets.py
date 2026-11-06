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

from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

PATTERNS = (
    (re.compile(r"(?i)\w*(?:api[_-]?key|token|secret|password|passwd)\w*\s*[:=]\s*\S{6,}"),
     _lt("a named key, token or password")),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), _lt("a bearer token")),
    (re.compile(r"\b(?:sk|ghp|gho|ghs|github_pat|xox[abprs])[-_][A-Za-z0-9_\-]{12,}"), _lt("an API key")),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _lt("an AWS access key")),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), _lt("a JWT")),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), _lt("a private key")),
    (re.compile(r"\b[0-9a-f]{48,}\b"), _lt("a long hexadecimal secret")),
)


def credential_reason(text):
    """What in the text looks like a credential (a lazy translation: str() renders it in the language of
    the environment), or None when nothing does."""
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
            what = reason._translate(env.lang or '') if hasattr(reason, '_translate') else reason
            raise UserError(env._("The text holds what looks like %s: a credential never goes in the memory. "
                                  "Remove it and write again.", what))
