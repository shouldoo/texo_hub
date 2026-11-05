# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Open Knowledge Format (OKF v0.2) for the memory of the hub.

OKF (https://github.com/GoogleCloudPlatform/open-knowledge-format, SPEC.md) is a bundle of
markdown files with YAML frontmatter: concepts with a required type, an index.md per level
for progressive disclosure, a log.md for the history. The hub keeps its records in Odoo,
native and custom, with their own field names; this module is the one place that names
them the OKF way when an agent reads them back:

- a record is a concept, addressed as <kind>/<id> (rules/12, facts/3, projects/5);
- the context pack is the index: titles and one-line descriptions, the text on request;
- the updates of a project and the chatter of a task are the log;
- state, verification and expiry become status, verified and stale_after; the documents a
  record cites become its sources.

Plain functions, no model: every module of the hub renders with them.
"""
import json
import re
from datetime import date, datetime, timedelta

OKF_VERSION = '0.2'
# The kind of each model in a concept id: the path of the concept in the bundle.
KINDS = {
    'memory.note': 'rules', 'memory.lesson': 'lessons', 'ir.attachment': 'documents',
    'project.project': 'projects', 'project.task': 'tasks', 'res.partner': 'customers',
}
MODELS = {kind: model for model, kind in KINDS.items()}
# A note of the memory is a rule, a fact or a procedure: its kind is its own (_okf_kind).
MODELS.update({'facts': 'memory.note', 'procedures': 'memory.note'})


def register(model, kind):
    """A module adds a kind of concept (texo_sources: sources/12, a card of the external sources)."""
    KINDS[model] = kind
    MODELS[kind] = model


# The lifecycle of the hub (draft, active, superseded, archived) in OKF words.
STATUS = {'draft': 'draft', 'active': 'stable', 'superseded': 'deprecated', 'archived': 'deprecated'}
# An actor (OKF § 7): <producer>/<version> for an agent or a tool, human:<id>, process:<id>.
ACTOR = re.compile(r'^(?:(?:human|process):[^\s:]+|[\w.-]+/[\w.:+-]+)$')
# The keys of OKF first, in the order of the specification; the hub's own after them.
KEYS = ('type', 'title', 'description', 'resource', 'tags', 'status', 'generated', 'verified', 'stale_after', 'sources')
CONCEPT = re.compile(r'^/?(?P<kind>[a-z]+)/(?P<id>\d+)(?:\.md)?$')
DESCRIPTION = 160


def concept_id(record):
    """rules/12: the kind of the record (of its model, or its own) and its id."""
    kind = record._okf_kind() if hasattr(record, '_okf_kind') else KINDS[record._name]
    return f"{kind}/{record.id}"


def link(record):
    """The bundle-relative link to the concept of a record (OKF § 6.1)."""
    return f"/{concept_id(record)}.md"


def parse(concept):
    """(model, id) of a concept id or link: rules/12, /facts/3.md."""
    match = CONCEPT.match((concept or '').strip())
    if not match or match['kind'] not in MODELS:
        raise ValueError(f"A concept is one of {', '.join(sorted(MODELS))} with its id, as facts/12; not {concept!r}.")
    return MODELS[match['kind']], int(match['id'])


def actor(value):
    """The actor a client says it is, when it is one; None otherwise."""
    value = (value or '').strip()
    return value[:120] if ACTOR.match(value) else None


# The superuser is Odoo itself (data files, migrations, crons), never a person: what it wrote
# or checked is machine-confirmed, not human-reviewed (OKF § 5.3).
SYSTEM = 'process:odoo'
# A person who must not be named: the author of a lesson, which points back to no one.
ANONYMOUS = 'human:anonymous'


def human(user):
    """A person as an actor; the superuser as the process it is."""
    if not user:
        return None
    return SYSTEM if user._is_superuser() else f"human:{user.login}"


def tool(module):
    """The hub itself as the producer of what an agent wrote without naming itself."""
    from odoo.modules.module import get_manifest  # noqa: PLC0415
    return f"{module}/{get_manifest(module).get('version') or 'unknown'}"


def generated(origin, author, by=None, at=None, module='texo_memory', anonymous=False):
    """generated (OKF § 5.2): who wrote the current content, and when. A person writes as
    human:<login> (anonymous: as a person never named, on the day only); an agent as the actor
    it gave (by), else as the hub tool it called."""
    if anonymous and at:
        at = at.date() if isinstance(at, datetime) else at
    if origin == 'person':
        who = ANONYMOUS if anonymous and not author._is_superuser() else human(author)
    else:
        who = actor(by) or tool(module)
    return {'by': who, 'at': timestamp(at)} if who else None


def verified(user, at):
    """verified (OKF § 5.2): one check by a person on a day."""
    return {'by': human(user), 'at': timestamp(at)} if user and at else None


def timestamp(value):
    """An ISO 8601 instant in UTC (OKF § 5): a day is its midnight."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat() + 'Z'
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def stale_after(*candidates):
    """The earliest instant after which the concept is stale, of dates and datetimes."""
    instants = [c if isinstance(c, datetime) else datetime.combine(c, datetime.min.time()) for c in candidates if c]
    return timestamp(min(instants)) if instants else None


def day_after(value):
    return value + timedelta(days=1) if value else None


def status(state):
    return STATUS.get(state, 'stable')


def description(text, limit=DESCRIPTION):
    """One line that sums up a text: its first sentence, cut at limit."""
    text = " ".join((text or '').split())
    if not text:
        return None
    # a period after a number is a step («1. Check the goods»), not the end of the sentence
    sentence = re.split(r'(?<=[^\d\s][.!?])\s', text, maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[:limit - 1].rstrip() + "…"


def frontmatter(meta):
    """The YAML block of a concept. Each value is written as JSON, which is YAML: a string
    is double-quoted and escaped, a mapping or a list is in flow style; nothing is lost."""
    lines = ['---']
    ordered = [k for k in KEYS if k in meta] + [k for k in meta if k not in KEYS]
    for key, value in ((k, meta[k]) for k in ordered):
        if value is None or value == [] or value == {}:
            continue
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append('---')
    return "\n".join(lines) + "\n"


def concept(meta, body=''):
    """A concept document: frontmatter, a blank line, the markdown body."""
    if not meta.get('type'):
        raise ValueError("An OKF concept needs a type.")
    body = (body or '').strip()
    return frontmatter(meta) + (f"\n{body}\n" if body else "")


def entry(title, target, text=None):
    """One line of an index: a link to a concept and its description."""
    title = (title or '').replace('[', '(').replace(']', ')')
    return f"* [{title}]({target})" + (f" - {text}" if text else "")


def index(sections, version=False):
    """An index.md (OKF § 8): sections of entries, no frontmatter but the okf_version of a
    bundle root. sections: [(heading, [line, ...])], empty sections left out."""
    parts = [frontmatter({'okf_version': OKF_VERSION}).rstrip()] if version else []
    for heading, lines in sections:
        if lines:
            parts.append(f"# {heading}\n\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


def log(title, entries):
    """A log.md (OKF § 9): entries grouped by ISO day, newest first.
    entries: [(day, kind, text)], kind the leading bold word (Update, Note, ...)."""
    days = {}
    for day, kind, text in sorted(entries, key=lambda e: str(e[0]), reverse=True):
        text = " ".join((text or '').split())
        days.setdefault(str(day)[:10], []).append(f"* **{kind}**: {text}")
    parts = [f"# {title}"] + [f"## {day}\n" + "\n".join(lines) for day, lines in days.items()]
    return "\n\n".join(parts) + "\n"


def bundle(files):
    """The answer of a route asked in OKF: the files of a (partial) bundle, path and text."""
    return {'format': 'okf', 'okf_version': OKF_VERSION,
            'files': [{'path': path, 'text': text} for path, text in files]}


def render(answer):
    """A bundle as one text for an agent: each file after a comment with its path."""
    return "\n".join(f"<!-- okf: {f['path']} -->\n{f['text']}" for f in answer['files'])
