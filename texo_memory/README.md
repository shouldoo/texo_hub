# Texo - Memory

Odoo 20.0 · LGPL-3

The working memory of an organisation, kept in its own Odoo Community. The project lives in
Odoo itself: its description, its milestones, its updates, its tasks with their chatter. This module
adds what Odoo does not hold: what the memory knows of the organisation, a customer, a project or a task
(rules, facts, procedures), the lessons learned without the customer, and
which attachments of its records are documents of the memory, with their converted text. Agents read it through the Texo token (see `texo`) and
write it after the person's confirmation; the roles of the hub decide who reviews what.

## Two kinds of memory

| Model | What it holds | Who reads it | What happens at a customer's opt-out |
|---|---|---|---|
| `memory.note` | what the memory knows of the organisation (the company), a customer, a project or a task, one note at a time, of three kinds (`kind`, the `type` of its OKF concept): a **rule** (what an agent must always or never do; never on a task), a **fact** (what the record is), a **procedure** (how an operation is done, step by step) | who works in the company, or can read the project, customer or task it belongs to (domain operator `access` on the anchor) | deleted |
| `memory.lesson` | knowledge that belongs to no customer: `finding` (written by the agent from the work on a project), `lesson` (curated by a lead), `procedure`; of one of our companies (`company_id`, the current one by default) or, empty, shared by all | every hub member of that company, whatever projects they can see | kept |

A lesson has no field pointing to a customer, project, task or rule: nothing in it can lead back to
the work it was learned on.

**The organisation itself** is the company (`company_id`, the fourth anchor of `memory.anchor.mixin`), not
a customer: a note, a document or a context pack asked with no task, project or customer goes to the
current company, or to `company_id` when the user works in several. It is the root of the OKF bundle,
above the customers and their projects. A record on the company, or on a project whose customer is one
of our companies, has no `customer_id`, and the opt-out refuses our own companies. The home project of a
company (`texo_project`) stays, for the internal work: its tasks and updates.

Every note and lesson carries its state, `draft`, `active`, `superseded` or `archived`, with
`supersedes` / `superseded_by`, `expires`, `valid_from` (the first day a fact or a procedure holds, when it is
not the day it is written) and `superseded_on` (the day it was superseded or archived: with the two others,
what the memory knew on a given day); a note also `verified` and `verified_by_id` (for a rule, the
confirmation of a lead), a lesson `verified` as free text and `applies_to`. Only an active rule binds the
agent. Nothing is deleted: a newer one supersedes the older.

A rule is typed for the agent that reads it (a fact and a procedure may carry activities too):

- `severity`: how it binds, `never` (a prohibition), `must` (an obligation, the default) or `prefer`
  (what the agent does unless the person decides otherwise);
- `rule_activity_ids` («Applies to»): the work it concerns, among the activities of
  `memory.note.activity` (`analysis` and `communication` in the data of the module; the seed of a
  pack adds those of its sector, such as `code` or `deploy`, and a lead the organisation's own in
  *Memory > Rule Activities*). None means
  every activity. A session that passes its activity gets the rules of that activity and those of
  every activity; the field is not `activity_ids`, which is the to-do list of the chatter.

## Notes: rules, facts and procedures

One model, three kinds, one schema: title, text (plain text), `section_id`, `keywords`, `applies_to`, state,
`verified` and `verified_by_id`, `expires`, `origin` and `generated_by`, the document it was taken from
(`document_id`, `source_ref`, `source_checked`), `supersedes` / `superseded_by`. The kind decides the
behaviour:

| Kind | OKF `type` | What it is | How it is written |
|---|---|---|---|
| `rule` | `Rule` | what an agent must always or never do; it binds | a member's draft until a lead activates it; `severity`, activities; never on a task |
| `fact` | `Fact` | what the record is: who decides at the customer, how its warehouse is organised, what was agreed on a task | as it is, active and verified today, by whoever may write on its anchor |
| `procedure` | `Playbook` | how an operation is done, step by step; it describes, it does not bind: what in it binds is a rule | as a fact |

Two sessions never overwrite each other: `memory/note_append` adds a dated, signed paragraph to a fact or
a procedure with the row locked; `memory/note_update` replaces the text only with the `version` returned
by `memory/read` (a fingerprint of the text: any change since the reading refuses the replacement). A
write is idempotent: the same title and text of the same kind already live on the same record (a session
that proposes a note twice, a call retried) give that note back with `existing: true`, nothing is written
(`content_hash`, whitespace folded); the same for a finding (`memory/lesson`, finding and solution) and for
the last internal note of a task (`project/task_note`). The
context pack gives the live facts and procedures of every level of the chain, the task included, by
their title, section, the day they were verified and `stale` (`unverified` after 180 days, `expired`,
`source_changed`); the text comes with `memory/read`. An expired one leaves the pack and the search.
The notes of a customer go with its opt-out; those of the organisation stay.

**Sections** (`memory.section`, extensible like the activities: `profile`, `operations`, `compliance`,
`sector`, `offer` in the data of the module; a lead adds the organisation's own in *Memory > Sections*)
say which part of what the memory knows a note belongs to; the pack of the organisation is an index by
section, and the rules of the session list them.

## Roles

| Role (hub group) | Rules (facts and procedures: whoever may write on the anchor) | Lessons |
|---|---|---|
| Member | writes drafts; edits only their own drafts; a draft creates a review activity for the project manager (else for every hub lead) | reads; writes draft findings |
| Lead | everything a member does, and activates, supersedes, archives; a rule confirmed by a lead can be written `active` at once | creates, curates, changes the state |
| Administrator | as a lead | as a lead, plus the opt-out names |

The server enforces this whatever the client says: a member asking for an active rule or lesson
gets an `AccessError`.

## Findings: what a project learned, without the customer

`memory/lesson` (`_agent_lesson`) writes a `memory.lesson` of kind `finding` (`finding`, `solution`,
optional `tags`, `title`, `applies_to`, `verified`, `activities`) after the leak filter: a member's is a draft for
the leads, a lead's may be active at once. When the filter rejects the text, nothing is stored and the
error says why, so the agent rewrites it. `source_ref` (the task it comes from) only feeds the filter.
The lesson's creation date is truncated to the day, so it cannot be matched with the chatter of the
task.

The leak filter (`models/leak_filter.py`, one function for the write path, the housekeeping and the
tests) rejects: the name or reference of any customer (archived customers and the opt-out names
included; on 20.0 a customer is a top-level partner that is neither one of our companies nor a
user), pseudonym markers, e-mail addresses, URLs other than `github.com/OCA`, `github.com/odoo` and
the Odoo documentation, amounts of money, record references (`model/id`), task or ticket numbers
(`#NN`), the source reference given with it, and texts shorter than 20 or longer than 2000 characters.

`memory.optout.name` keeps the names of the customers that opted out, in clear because the filter
matches substrings; administrators only, never returned by a route.

## Documents: attachments of the records they belong to

A document of the memory is an attachment (`ir.attachment`, extended) of the task, the project or the
customer it belongs to; the organisation's own are on the company. It is a file, or a link (type
url) to an original that lives elsewhere (a shared drive, a web page). Its title is the name of the
attachment, its summary the description, both confirmed by the person; the people see it on the record,
with the permissions of that record, and in the menu *Memory > Documents*. The memory adds:

- `texo_document`: the attachment is in the memory (in the context pack of its level, in
  `memory/search` with `scope` `documents` or `all`, in `document/list`). The other attachments of a
  record stay out of it.
- `texo_read_on` and `texo_fingerprint`: when the original was read and its sha256
  then. A reading (`document/write` with `document_id`) that brings a different fingerprint, or a new
  content of the file on the record, sets `texo_changed_on`.
- the converted text (Docling, locally, on the person's machine) as a second attachment on the same record,
  `<name>.md` (`texo_text_of_id` points to the original), so later sessions read it without
  converting again. A file that is text already (Markdown, plain text) is its own text and needs none.
  With `texo_keep_text` off (a sensitive document) the memory keeps no text of it.
- `texo_created`: the memory brought the attachment in (a link, a file it received, a
  converted text). The opt-out of the customer deletes these; an attachment the people put on the
  record stays there, taken out of the memory.

The search ranks the documents by PostgreSQL full-text search over the title, the summary and the
text (a word present only in the text finds the document; a document without text is found by title
and summary only), computed at query time over the documents of the memory only. The text is indexed
whole in `index_content`: the native index of Odoo keeps only the ASCII words of a text, and an
accented word would be lost.

A long document is also searched by its **passages** (`memory.document.passage`, since 20.0.10.3.0). The
converted text is cut where the document itself is cut (`models/structure.py`): titles, parts, chapters,
sections, annexes and articles of a legal text, Markdown headings of any other; an article too long is cut at
its commas («commi 1-3»), what is still too long at paragraphs and sentences with a small overlap. Each passage
keeps its **path** («TITOLO I (DISPOSIZIONI GENERALI) > Art. 2 (Definizioni) > comma 1») and its offset in the
text, up to 400 passages per document, and has its own full-text vector (path, text, and the title of the
document with the least weight). A document ranks with the better of its whole vector and its best passage, and
holds every word of the question when one passage does: a rare word, an article number or an amount deep in an
act of hundreds of pages finds it. Every hit of a document names the passage that answered (`passage`: `path`,
`start`, `snippet`); the agent cites the path and reads the text from `start` with `document` (`offset`).
The passages are cut again when the text, the title or the state of the document change; a sensitive document
has none. Nobody reads them directly: the search reads them as the system, and gives one only with a document
the person may read.

A note that cites a document (`document_id` of `memory/note`) remembers when it was written or last
verified against it (`source_checked`): an original changed after that marks the note
`source_changed` (its `stale` value, after `expired` and before `unverified`) in the context pack, in
the review queue and for the housekeeping, until it is verified again (a rule by a lead) or activated.
A document stays a source: what it gives is written as notes that cite it.

A document has no state: it is in the memory or not. A lead takes one out (`document/remove`): what the
memory brought in goes, an attachment the people put on the record stays theirs.

The route `document/attachment` gives the file of an attachment the person may read (the access is
that of the record it is attached to; an attachment without a record is readable by its creator and
the administrators only), within 20 MB, for the local conversion.

## Rules of the session and context pack

`memory/rules` sends the rules every session starts with: the common rules of the hub (English, for
language models), then the active rules of the organisation, in creation order, each as
`- [severity] title: body` with its activities when it has some (`company_rules` lists them with
their ids), the activities the organisation knows (`activities`: code, name, description) and its
sections (`sections`). A
client reads them once, at the start; the `texo` MCP client puts them in the instructions
of the server. With `activity` only the rules of that activity and of every activity.

`memory.note._agent_context(task_id | project_id | nothing: the company, activity)` composes,
deterministically and within a budget, what an agent needs before touching a task: the task with its
description, its milestone and the latest messages of its chatter, the project with its description,
its milestones and its last update as `now` (from `texo_project`; its warnings `now_missing`
and `now_stale` join the warnings of the pack with the `project_id`), then for each level
of the chain task → parent tasks → project → customer (the organisation is a level of its own, the
company, in its pack, with the `sections`) the active rules, the facts and procedures by title and the
documents, the pending drafts (with their author; a lead sees their review queue first), warnings on
expired, unverified (180 days) or `source_changed` rules, and the lessons of the tags of the task and its project (see «Lessons in the pack»). A level the user cannot read is reported as
`not readable`. With `activity` (one code or several, comma-separated; an unknown one is refused with
the known ones) the rules of every level are those of that activity and of every activity, and the
pack says which (`activities`).

With `max_tokens` the pack is cut to about that many tokens (four characters each), in a fixed order: the
messages of the task, then the outlines of the facts, the procedures and the documents of each level, the
lessons, the description and the present of the project, and last the texts of the binding rules, shortened but
never dropped: a rule binds whatever the budget. The pack says the budget, its size and what was cut (`budget`;
in OKF, a line of the section Session of `index.md`).

## Search

- Notes (rules, their drafts included, facts and procedures), lessons and documents: PostgreSQL full-text
  search (`models/fulltext.py`, one helper for all), ranked together, on a stored `tsvector` with a GIN
  index: for a note or a lesson a generated column (title, then `keywords`, then the text, or finding and
  solution), for a document a column of `ir.attachment` written by the hub whenever the
  title, the summary, the keywords or the text change, indexed only where it is set (title, then summary
  and keywords, then the text). Plain words, Italian and English stems side by side. A word of four
  letters or more also matches as a prefix («migraz» finds «migrazione»). The results that hold every
  word come first; only to fill the limit, those that hold some, above a minimum rank (0.01). The words
  are reduced to letters, digits and underscores before they reach `to_tsquery`; a hit says which it is
  (`words`: `all` or `some`). The ORM has no
  full-text operator, so the ids come from SQL; the access rules are in that query (the sub-query of the
  ids the person may read, given by the ORM with its record rules: `fulltext.readable_ids`), so the
  candidates are readable records and not the best matches of everyone, and the records then go through
  the ORM as the person, the second check. A failure of the access check raises: the search never answers
  nothing for a permission it could not read. `applies_to` filters the lessons, expired ones stay out.
- **Keywords**: the writer of a lesson or a document gives synonyms, translations and other names
  (`keywords`); the search finds it by those words too, the meaning brought by the agent that writes.
  They go through the leak filter with the lesson. A task has its own (`texo_keywords`, given
  with the session note): in the vector of the episode they weigh B, above the description and the chatter.
- **`max_tokens`**: the results that fit in about that many tokens (four characters each), in the order of the
  search; an entry too long for what is left is skipped for the next; the first entry always stays, its snippet
  cut: an answer is never empty. The answer says the budget, its size and how many entries were skipped (`budget`).
- **`as_of`** (`YYYY-MM-DD`): the facts and procedures that held on that day, superseded and archived ones
  included: started by then (`valid_from`, else the day they were written), not yet expired, not yet superseded
  (`superseded_on`); a draft never held. «What was the tariff in February?» is asked this way.
- **The answer says how it ran**: `results`, then `mode` (the mode used: `lexical` here, whatever was asked),
  `rerank` (what the reranker did: `off`, `skipped`, `applied`, `unavailable`; always `off` here) and
  `latency_ms`, so a degraded search is seen for what it is. `show_expired` gives the expired notes and lessons
  too, each with `stale: expired`, for a review.
- **`mode`** (`lexical`, `semantic`, `hybrid`): here the search is lexical whatever it says; the optional
  module [`texo_vector`](../texo_vector/README.md) gives it its meaning (vectors for the
  episodes, the facts, the procedures, the lessons and the documents, fused with the words; never the rules) and marks every hit with
  which search found it (`match`).

## What the pack carries

The pack is an outline where the text is not needed to bind: a rule `never` or `must` comes with its text
(at most 1,500 characters, `truncated` beyond), a rule `prefer` with its title and `body_omitted`, a lesson
with its id, title, tags and `applies_to`. The agent reads the rest with `memory/read` when the work
touches it.

## Lessons in the pack

A lesson is indexed by the **native tags of the projects** (`project.tags`, `tag_ids`: a module, a
version, an area) and by the activities it helps (`lesson_activity_ids`, the activities of the rules;
none means every activity). The context pack gives the active lessons that share a tag with the task
or its project, those that share more first, the newer first among equals, at most five; with the
activity of the session, those of that activity and of every activity. A task whose task and project
have no tags gets no lessons: the pack no longer guesses from the words of a title, which brought
lessons about something else and cost a full-text search at every pack. To get the lessons of a
project, tag it as its lessons are tagged; to find any other, search (`memory/search`).

### The episodes

The description and the chatter of a task are the episodic memory of a project: what was asked, what was
found, what was done. `memory/search` with `scope` `tasks` finds them («has something like this happened
before?»): a full-text vector of every task (title with the highest weight, description, the human messages
of the chatter; what Odoo tracks stays out), kept by the module when the task or its chatter changes and
computed once for the tasks of before at install or update, ranked by `fulltext.py` like the rest, as the
user: the record rules of `project.task` decide which episodes exist, archived tasks stay out. The episodes
are not part of `all`: the memory is one thing, the work another. A hit carries the summary of the task,
its concept id (`tasks/7`) and the first words of the description.

`memory/lesson` takes the tags by name: an existing tag is matched whatever its case, a missing one is
created (the tags are the vocabulary of the organisation; the consolidation merges two that say the
same). A tag goes through the leak filter with the lesson.

A lead's pack also carries `pending_lessons`: the draft findings waiting for a decision.

## Housekeeping and consolidation

The cron **Memory: weekly housekeeping** (`memory.lesson._cron_housekeeping()`) does three things and
decides nothing on its own:

- re-runs the leak filter on every draft or active lesson: a customer created after a lesson was
  written may be named in it; such a lesson is archived with a note in its chatter;
- looks for near-duplicates among the lessons with a tag in common, or both without tags (`difflib` ratio, 0.6 by default) and
  gives every hub lead one activity per pair, naming the other lesson, never twice for the same pair:
  the person merges or supersedes, nothing is merged automatically;
- gives the reviewers of every active rule that is expired or not confirmed for 180 days one activity
  (`memory.note._cron_housekeeping()`), never twice for the same reason.

The consolidation itself is done with the person, from the review queue of `memory/review`: draft
rules to decide, stale rules to re-check (`memory/confirm` resets the confirmation date and may set an
expiry), the projects with open tasks whose present is missing or older than 30 days
(`projects_without_now`: every readable project for a lead, the managed ones for a member), draft
lessons and near-duplicate lessons for the leads. The rules sent by `memory/rules` tell the agent how to run it.

## Using it in Odoo

The models are written for the agents, but the people consult, correct and update them from the backend.
Menu *Memory*:

- **Search the Memory**: a question, a scope (all the memory, rules, facts, procedures, documents, lessons, or
  the episodes of the tasks) and, with `texo_vector`, a mode (words, meaning, both). The same
  ranking as `memory/search`, with the kind of each result, what found it (every word, some words, meaning,
  both), an excerpt and a button to open the record.
- **To Review**: the queues of the weekly review with their counts, each opening its records: draft rules,
  notes to check (`stale`: active and expired, not verified for 180 days, or with a changed source document),
  changed documents, draft lessons and near-duplicates (leads), projects without a recent update. Other
  modules add their queues (`texo_sources`: candidates, cards to approve and to review, channels
  overdue).
- **Knowledge**: rules, facts, procedures, documents, lessons, with the same filters where they make sense
  (draft, active, superseded; to check, expired, expiring in 30 days; written by an agent or a person; mine;
  of the organisation, a customer, a project, a task; modified in a period) and grouping by kind, state,
  section, customer, project, author. The lists act on a selection: verified today, activate, archive. A
  document shows its converted text in the form; a sensitive one says the memory keeps none.
- **Configuration** (leads): sections, rule activities; opt-out names and customer opt-out (administrators).

On the work records: buttons with the counts of the memory on a **project** (rules, facts and procedures;
documents; the lessons that share a tag with it), a **customer** and the **organisation** (the company form);
on a **task** the page *Memory* with its search keywords and its facts and procedures.

## Opt-out of a customer

Menu *Memory > Configuration > Customer Opt-out* (hub administrators). The wizard shows what will be deleted (the
rules of the customer and their projects with their files, the documents of the memory on the
customer, its projects and their tasks), asks the customer's name as confirmation, then deletes the
rules and what the memory brought in (links, files it received, converted texts; an attachment the
people put on a record stays, taken out of the memory), adds the customer's name and reference
to the opt-out list, archives the partner and returns a certificate (counts, who, when, a sha256 of
the certificate) that it also posts as an internal note on the task that tracks the request. Lessons
and findings stay: they hold nothing of the customer. Tasks, timesheets and accounting records are
company records and stay out of the wizard's scope.

## Open Knowledge Format

The records keep their Odoo names; an agent reads them back named as
[Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) (OKF v0.2:
markdown with YAML frontmatter, an `index.md` for progressive disclosure, a `log.md` for the history),
through `format: okf` on the reading routes and `texo/okf.py`, the one place of the mapping:

| OKF | In the hub |
|---|---|
| concept id (`<kind>/<id>`) | `rules/<id>`, `facts/<id>`, `procedures/<id>` (`memory.note`, by its kind), `lessons/<id>`, `documents/<id>` (`ir.attachment`), `projects/<id>`, `tasks/<id>`; every summary carries it as `concept`, `read` takes it |
| `type` | `Rule`, `Fact`, `Playbook` (the `kind` of a note), `Finding` / `Lesson` / `Playbook` (the `kind` of a lesson), `Document`, `Project`, `Task` |
| `status` | `state`: `draft` → `draft`, `active` → `stable`, `superseded` and `archived` → `deprecated` |
| `generated` (`by`, `at`) | `origin` and `generated_by`: a person as `human:<login>`, an agent as the `<producer>/<version>` it gave, else the hub tool it called (`texo_memory/<version>`); Odoo itself (the superuser: data files, migrations) as `process:odoo`, never as a person; `at` the last write. A lesson names no one: its person is `human:anonymous`, its time the day only |
| `verified` (`by`, `at`) | a note: `verified` and `verified_by_id` (for a rule, the confirmation of a lead); by the superuser it is `process:odoo`: machine-confirmed, not human-reviewed |
| `stale_after` | the earliest of the day after `expires`, 180 days after the check and the change of the cited document; `stale` gives the reason (`expired`, `unconfirmed`, `unverified`, `source_changed`) |
| `valid_from`, `valid_to` | keys of the hub: the first day a fact or a procedure holds, and the earliest of its expiry and the day it was superseded or archived |
| `sources` | the cited document (`document_id`, with its `last_modified`) and `source_ref`, for every note |
| `tags` | the activities of a rule, the project tags of a lesson |
| `index.md` | the context pack: every level of the chain with its rules, facts, procedures and documents by title and one line (the organisation by section), the lessons, the pending items, the warnings, the activities of a rule, the expiry of a fact, a document whose original changed; the rules that bind (`never`, `must`) come in full, in a file of their own unless their line already carries their whole text |
| `log.md` | the updates of a project and the milestones reached (`project/log`; in the pack the latest three), the chatter of a task |

Keys of the hub's own (`severity`, `section`, `anchor`, `keywords`, `applies_to`, `version`, `checked`) follow the
OKF keys, as the specification allows. A lesson carries no anchor and no author.

## Routes

All take the user's hub token as bearer and run as the user. A client error answers 422 with the
reason, a refusal 403, a record the user cannot read 404.

| Route (`POST /texo/v1/memory/...`) | Parameters | Returns |
|---|---|---|
| `rules` | `company_id` (optional), `activity` (optional) | the role of the user and the rules of the session: the common rules, then the active rules of the organisation (`company_rules`), and the activities of the organisation (`activities`) |
| `context` | `task_id` or `project_id` (neither: the company, or `company_id`), `messages` (default 5), `activity` (optional), `format` (`json`, `okf`) | the context pack; in OKF, the files of the bundle (`index.md`, the task and the project, the binding rules, `log.md`) |
| `search` | `query`, `related_terms`, `scope` (`all`, `rules` or `notes`, `facts`, `procedures`, `documents`, `lessons`; `tasks` for the episodes), `applies_to` (lessons), `limit` (max 20) | rules the user may read (first), then documents and lessons by score, with a snippet; with `tasks`, the tasks the user may read ranked by title, description and chatter |
| `read` | `note_id` (`fact_id` as a synonym) or `lesson_id`, or `concept` (`rules/12`, `facts/3`, `procedures/8`, `lessons/5`, `documents/9`, `projects/2`, `tasks/7`; a concept whose kind is not the record's is refused), `max_chars` (200 to 20000), `format` (`json`, `okf`) | one note (with its `version`, unless cut) or lesson; a concept of another kind as its own route gives it |
| `note` | `name`, `body`, `kind` (`rule`, the default, `fact`, `procedure`), one anchor among `task_id` (not a rule), `project_id`, `partner_id` (none: the organisation, the company or `company_id`), `section` (a code), `keywords`, `applies_to`, `expires`, `valid_from`, `document_id` (the document of the memory it comes from), `source_ref`, `generated_by` (the agent, `<producer>/<version>`); for a rule `state` (`draft` or, for a lead, `active`), `severity` (`never`, `must`, `prefer`; default `must`), `activities` (codes, a list or comma-separated; none: every activity) | a rule: its summary; a fact or a procedure: the note, active, verified by the person |
| `note_append` | `note_id`, `text`, `keywords` | a fact or a procedure, with a dated and signed paragraph more |
| `note_update` | `note_id`, `body` with `expected_version`, `name`, `section`, `keywords`, `applies_to`, `expires`, `valid_from`, `verified` (a rule only by a lead) | the note |
| `fact`, `fact_append`, `fact_update` | as `note` with `kind` `fact`, `note_append`, `note_update` (`fact_id` for `note_id`) | kept for the clients that call them |
| `lesson` | `finding`, `solution`, `tags` (names, a list or comma-separated), `activities` (codes), `keywords`, `title`, `applies_to`, `verified`, `state` (`draft` or, for a lead, `active`), `source_ref` (for the leak filter only), `generated_by` | the finding written |
| `state` | `note_id` (`fact_id`) or `lesson_id`, `state` (`active`, `superseded`, `archived`), `superseded_by_id` | a rule or a lesson: lead only; a fact or a procedure: its author or a lead |
| `review` | — | the review queue of the person: draft rules, stale rules, projects without a recent update; for a lead also draft lessons and near-duplicate lessons |
| `document/list` (`/texo/v1/document/...`) | one of `task_id` / `project_id` / `partner_id` (none: the company, or `company_id`) | the documents of that record |
| `document/read` | `document_id`, `text` (default false), `max_chars`, `offset`, `format` (`json`, `okf`) | the document, with a slice of its text when asked (`text_next_offset` while more remains) |
| `document/write` | `document_id` (an attachment of a record the person reads: it becomes a document, or a document gets its new reading; a different `fingerprint` sets `changed_on`), or `name` with `url` (a link) or `data` (a file in base64, max 20 MB) and one anchor (none: the company, or `company_id`); `summary`, `keywords`, `read_on`, `fingerprint`, `keep_text`, `text` (the converted text, max 5 MB) | the document written |
| `document/remove` | `document_id` | lead only: the document out of the memory |
| `document/attachment` | `attachment_id` | the file of an attachment the person may read: name, type, size, sha256, record, content in base64 (max 20 MB) |
| `confirm` | `note_id`, `expires` (optional, `YYYY-MM-DD`) | a note re-checked today: an active rule by a lead, a fact or a procedure by whoever may write it |
| `admin/seed` (`/texo/v1/admin/seed`) | `industry` (the name of the pack), `activities` and `sections` (`code`, `name`, `description`, `sequence`), `rules` (`key`, `name`, `body`, `severity`, `activities`, `section`, `keywords`, `applies_to`), `project_templates` (`key`, `name`, `description`, `tasks` with `name` and `description`), `company_id`, `lang` (default `en_US`), `apply` (default false) | administrator only: every item of the seed with its status (see «The seed of an industry») and the counts; written only with `apply` |

The same logic is available as methods on the models (`_agent_context`, `_agent_search`,
`_agent_read`, `_agent_note`, `_agent_rules_text`, `memory.lesson._agent_lesson`, `_agent_set_state`,
`ir.attachment._texo_write` and the other `_texo_*` methods of the documents), for an adapter that exposes it another way.

## The seed of a pack

The module ships only what every organisation has: the activities `analysis` and `communication`, the
sections `profile`, `operations`, `compliance`, `sector`, `offer`. What a sector adds (its activities and
sections, the rules every organisation of the sector starts with, its project templates) is the seed of
its skill pack (`packs/<name>/seed.toml` of `texo_marketplace`), which the `texo seed` command of `texo_core` sends
to `admin/seed` (`memory.seed._agent_seed`). The field `industry` of the route is the name of the pack: it keeps
the name it had when the packs were industry repositories, since it is the first part of every `seed_key`.

Every item has a stable key (a `code` for activities and sections, a `key` for rules and templates); the
record it becomes carries `seed_key` (`<pack>/<kind>/<key>`) and the fingerprint of the values the seed
last wrote (`seed_fingerprint`). Each run answers, item by item:

| Status | What happens |
|---|---|
| `created` | missing: written with `apply` |
| `updated` | the seed changed and nobody touched the record since the last run: rewritten with `apply` (`changes` names the fields) |
| `unchanged` | the record already says what the seed says |
| `kept` | `changed_here`: a lead changed the record since the seed wrote it, the record stays as it is (`changes` names what differs); `not_from_seed`: an activity or a section with the same code was written by hand, never taken over |
| `left_seed` | a record of this pack that the seed no longer has: reported, never deleted |

The rules of the seed are rules of the organisation (the company, or `company_id`), active at once and
verified by the administrator who applies them after reading the dry run. A project template is a
project with `is_template`, its tasks rewritten from the seed while nobody touched it; the administrator
of the hub needs no project manager rights for it.

## Demo data

A database created with the demo data gets one record per kind of memory, in Italian, on the main
company: the rule «Nessun invio al cliente senza la persona» (`never`, activity `communication`,
active) taken from the document «Manuale delle comunicazioni ai clienti» (a link, with its converted
text next to it), the fact «Orari e reperibilità», the procedure «Aprire un progetto» taken from the
document «come-si-apre-un-progetto.md» (a Markdown file, its own text), both in the section
`operations`, and the lesson «Un campo calcolato non salvato non si cerca» (`orm`, active). A
database without the demo data, like an instance in use, gets none of them.

## Tests

```bash
odoo -c <conf> -d test_cohub20 -i texo_memory --test-tags /texo_memory --http-interface=127.0.0.1 --stop-after-init
```

61 tests (one only with the demo data): each class of leak, a finding written directly and the refusal on a leak, no link from a
lesson to the work, a member without project access reads the lesson but not the rule, roles on rules
and lessons, a note is a rule and never on a task, the severity and the activities of a rule, the
rules of the organisation in the rules of the session, the pack and the rules filtered by the
activity of the session, the context pack along the chain with the rules of each level, the project and its present,
and stale warnings, search in
both languages, documents as attachments (links, files, texts, the converted text, an accented word, the removal) and their sources, the home of the company, the housekeeping (a customer
created later, near-duplicates, stale rules, no activity twice), the review queue with the projects
without a recent update, the confirmation,
the routes with their status codes, the opt-out, the demo data reaching the agent, the lessons of the pack by tag and activity, the search that puts the lessons with every word first, by prefix and by keywords, the stored vector of the documents, the outline of the pack, the facts (pack, append, version, stale and expired, who archives, the search past what the person may not read, the opt-out, the routes), the OKF rendering (rules, facts and lessons as concepts with their trust and sources, a fact gone stale with its document, the pack as an index with the binding rules and a log, the routes by concept id).

## Changelog

### 20.0.1.4.0

- `max_tokens` on `memory/context` (the pack cut in a fixed order: the messages of the task, the outlines of the
  facts, procedures and documents, the lessons, the texts of the project, the texts of the binding rules, never a
  rule dropped; the pack says what was cut) and on `memory/search` (the results that fit, never none).

### 20.0.1.3.0

- `valid_from` on the notes and `superseded_on` set by a change of state; the search takes `as_of`: the facts and
  procedures that held on a day, superseded ones included; OKF keys `valid_from` and `valid_to`.

### 20.0.1.2.0

- A note, a lesson, the summary or the keywords of a document that hold what looks like a credential are
  refused (`texo/models/secrets.py`); a read-only token is refused on every write.

### 20.0.1.1.0

- The answer of `memory/search` says how the search ran: `mode` (the one used), `rerank` (off, skipped,
  applied, unavailable), `latency_ms`; `show_expired` gives the expired notes and lessons too, marked stale.
- Idempotent writes: the same note (title and text) already live on the same record, or the same finding, gives
  the existing record back with `existing: true`, nothing is written (`content_hash` on notes and lessons).
- The access rules are in the full-text query (`fulltext.readable_ids`): the candidates are readable records,
  however many stronger matches of other customers there are; the ORM pass is the second check.
- The tasks of a project template and the task templates are not episodes: out of the search and of the vectors.
- The gauges of the memory in `GET /texo/metrics`: notes by kind and state, stale rules, lessons, documents,
  passages, episodes.

### 20.0.1.0.2

- The seed comes from a skill pack of the marketplace: its texts say pack, the field `industry` of `admin/seed`
  keeps its name.

### 20.0.1.0.1

- The seed creates the tasks of a project template without assignees.

### 20.0.1.0.0

- First release in Texo.

## Author

Daniele Lucarelli
