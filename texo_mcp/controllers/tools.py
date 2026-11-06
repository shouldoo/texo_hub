# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The tools of the MCP server: name, description, input schema, the route that serves it.

Each tool calls the controller method of its route, so the MCP server and the routes give
the same answers, with the same checks. English, for language models; not translated. The
descriptions follow those of the `texo` CLI of texo_core, the local client over stdio.
"""
INTEGER, STRING = {'type': 'integer'}, {'type': 'string'}
STRINGS = {'type': 'array', 'items': STRING}
CONFIRM = {'type': 'boolean', 'description': "true only after the person agreed in the session"}
STATES = ['active', 'superseded', 'archived']
UPDATE_STATUSES = ['on_track', 'at_risk', 'off_track', 'on_hold', 'done']
SEVERITIES = ['never', 'must', 'prefer']
SCOPES = ['all', 'rules', 'notes', 'facts', 'procedures', 'lessons', 'documents', 'tasks', 'sources']
MODES = ['lexical', 'semantic', 'hybrid']
KINDS = ['rule', 'fact', 'procedure']
SECTION = {'type': 'string', 'description': "the section of the note: profile, operations, compliance, sector, offer "
                                            "or another of the organisation's (the pack of the organisation lists them)"}
FORMAT = {'type': 'string', 'enum': ['json', 'okf'],
          'description': "okf: the files of an Open Knowledge Format bundle (markdown with YAML frontmatter)"}
GENERATED_BY = {'type': 'string', 'description': "who you are, as <producer>/<version> (e.g. claude-code/2.1): the "
                                                 "concept says which agent wrote it"}


def tool(name, description, properties=None, required=(), route=None, write=False):
    """A tool; route is (controller key, method name), the name of the tool by default."""
    properties = dict(properties or {})
    if write:
        properties['confirm'] = CONFIRM
        required = tuple(required) + ('confirm',)
    schema = {'type': 'object', 'properties': properties}
    if required:
        schema['required'] = list(required)
    return {'name': name, 'description': description, 'inputSchema': schema, 'route': route, 'write': write}


TOOLS = [
    tool('whoami', "Who I am in the coordination Odoo and my hub role (member, lead, admin). Call it first.",
         route=('hub', 'whoami')),
    tool('rules', "The rules of the session (the common ones, then the active rules of the organisation, each with "
                  "its severity), with my role and the activities of the organisation. They are already in the "
                  "instructions of this server: call it again only after a rule changed. With activity, only the "
                  "rules of the organisation that concern it.",
         {'activity': STRING}, route=('memory', 'rules')),
    tool('my_work', "My open tasks.", {'limit': INTEGER}, route=('project', 'my_work')),
    tool('task', "One task: summary, description, subtasks, latest messages, worklog. With format okf, the task as "
                 "an OKF concept (tasks/<id>.md) and its chatter as its log.",
         {'task_id': INTEGER, 'messages': INTEGER, 'format': FORMAT}, ['task_id'], route=('project', 'task')),
    tool('task_note', "After the person's yes: an internal note in the chatter of a task (plain text), written to "
                      "be found later: the symptom or request in the words of who reported it, the technical cause, "
                      "what was done or decided and why, the state. keywords: 5 to 10 synonyms and other names "
                      "(Italian and English, acronym and expansion, the word of a non-technical person; no generic "
                      "words), merged into the search keywords of the task, which the search weighs above the chatter.",
         {'task_id': INTEGER, 'body': STRING, 'keywords': STRINGS}, ['task_id', 'body'], route=('project', 'task_note'),
         write=True),
    tool('context', "The context pack of a task or project: the task with its description, milestone and latest "
                    "messages; the project with its description, milestones (the roadmap) and last update (now: its "
                    "present); the chain with the active rules of each level (the text of a prohibition or an "
                    "obligation, the title of a preference), its facts and procedures by title and its documents; draft rules, warnings (now_missing, "
                    "now_stale, stale rules) and the lessons that share a tag with the task or its project, by title. "
                    "Read it before you start the work. With neither, the pack of the organisation itself (the "
                    "company, or company_id), by section. Pass the activity of the session (analysis, "
                    "communication or another of the organisation's; several comma-separated) to get only the rules that "
                    "concern it. With format okf, the pack as an Open Knowledge Format bundle: index.md (every level "
                    "with its rules, facts, procedures and documents by title and one line, the lessons, the pending items, the "
                    "warnings), the task and the project as concepts, the binding rules in full (a short one is whole in its "
                    "index line), log.md (the latest updates "
                    "of the project, the chatter of the task); read the rest with read and its concept id.",
         {'task_id': INTEGER, 'project_id': INTEGER, 'company_id': INTEGER, 'messages': INTEGER, 'activity': STRING,
          'format': FORMAT},
         route=('memory', 'context')),
    tool('search', "Search the rules, facts and procedures I may read, the documents of the memory (title, summary, "
                   "keywords and text) and the lessons of every project. Put the person's words in query and synonyms, "
                   "translations and other names in related_terms; search again with other words when the results miss. "
                   "Scope tasks searches the episodes instead: title, description and chatter of the tasks I may read "
                   "(has something like this happened before?), not part of all. Scope sources searches the active cards "
                   "of the external sources (where the module is installed; also in all): title, public persons, bodies, "
                   "places, themes, acts, abstract; for a period, a person or a channel use sources_find. mode: lexical "
                   "(the words), semantic (the meaning, where the hub has vectors: episodes, facts, procedures, lessons, "
                   "documents, cards; never the rules) or hybrid (both, the default "
                   "where the vectors are); a hit says which found it (match). A document names the passage that "
                   "answered (passage: path such as «Art. 43 > comma 2», start) and up to two more to read (passages): "
                   "read the text from start with document (text, offset), the next passage when the first does not "
                   "answer, and cite the path. show_expired: the expired notes and lessons too (each says stale "
                   "expired), for a review. The answer says how the search ran: mode (the one used: lexical when the "
                   "vectors did not answer), rerank (off, skipped, applied, unavailable), latency_ms.",
         {'query': STRING, 'related_terms': STRINGS, 'scope': {'type': 'string', 'enum': SCOPES},
          'applies_to': STRING, 'limit': INTEGER, 'mode': {'type': 'string', 'enum': MODES},
          'show_expired': {'type': 'boolean'}}, ['query'],
         route=('memory', 'search')),
    tool('read', "One note (note_id: a rule, a fact with the version to name in note_update, a procedure) or lesson in "
                 "full; or any concept of the memory by its OKF id (concept: rules/12, facts/3, procedures/8, lessons/5, "
                 "documents/9, projects/2, tasks/7; with the external sources, sources/12 for a card). With format okf, as an OKF concept: frontmatter (type, status, "
                 "generated, verified, stale_after, sources) and body.",
         {'note_id': INTEGER, 'fact_id': INTEGER, 'lesson_id': INTEGER, 'concept': STRING, 'max_chars': INTEGER,
          'format': FORMAT}, route=('memory', 'read')),
    tool('note', "After the person's yes: a note on the record it is about (task_id, project_id, partner_id; none: the "
                 "organisation itself, the company, or company_id), one per entry, with its section and keywords "
                 "(synonyms, other names). kind rule (the default): what an agent must always or never do, written only "
                 "when the person states one, never on a task (what concerns one task goes in a note on the task); "
                 "severity never (a prohibition), must (an obligation, the default) or prefer; activities: the codes of "
                 "the work it concerns (none: every activity); state active only for a lead, a member's rule is a draft. "
                 "kind fact: what the record is (who decides, how a process runs, what was agreed). kind procedure: how "
                 "an operation is done, step by step; what in it binds is a rule. A fact or a procedure is active at "
                 "once. A note taken from a document of the memory cites it with document_id: when the original changes, "
                 "the note is marked source_changed.",
         {'name': STRING, 'body': STRING, 'kind': {'type': 'string', 'enum': KINDS}, 'section': SECTION,
          'task_id': INTEGER, 'project_id': INTEGER, 'partner_id': INTEGER, 'company_id': INTEGER,
          'state': {'type': 'string', 'enum': ['draft', 'active']}, 'expires': STRING, 'source_ref': STRING,
          'document_id': INTEGER, 'severity': {'type': 'string', 'enum': SEVERITIES}, 'activities': STRINGS,
          'keywords': STRINGS, 'applies_to': STRING, 'generated_by': GENERATED_BY},
         ['name', 'body'], route=('memory', 'note'), write=True),
    tool('note_append', "After the person's yes: add a dated, signed paragraph to a fact or a procedure, with new "
                        "keywords; it becomes verified today.",
         {'note_id': INTEGER, 'text': STRING, 'keywords': STRINGS}, ['note_id', 'text'],
         route=('memory', 'note_append'), write=True),
    tool('note_update', "After the person's yes: replace the text of a note (body, with the version returned by read: "
                        "refused if it changed since), or its title, section, keywords, applies_to, expires; verified "
                        "true marks it checked today (a rule only by a lead).",
         {'note_id': INTEGER, 'expected_version': STRING, 'body': STRING, 'name': STRING, 'section': SECTION,
          'keywords': STRINGS, 'applies_to': STRING, 'expires': STRING, 'verified': {'type': 'boolean'}},
         ['note_id'], route=('memory', 'note_update'), write=True),
    tool('fact', "The note tool with kind fact, kept for the clients that call it: what a customer, a project or a "
                 "task is.",
         {'name': STRING, 'body': STRING, 'section': SECTION, 'task_id': INTEGER, 'project_id': INTEGER,
          'partner_id': INTEGER, 'company_id': INTEGER, 'keywords': STRINGS, 'applies_to': STRING, 'expires': STRING,
          'document_id': INTEGER, 'source_ref': STRING, 'generated_by': GENERATED_BY},
         ['name', 'body'], route=('memory', 'fact'), write=True),
    tool('fact_append', "note_append, kept for the clients that call it.",
         {'fact_id': INTEGER, 'text': STRING, 'keywords': STRINGS}, ['fact_id', 'text'],
         route=('memory', 'fact_append'), write=True),
    tool('fact_update', "note_update, kept for the clients that call it.",
         {'fact_id': INTEGER, 'expected_version': STRING, 'body': STRING, 'name': STRING, 'keywords': STRINGS,
          'applies_to': STRING, 'expires': STRING, 'verified': {'type': 'boolean'}}, ['fact_id'],
         route=('memory', 'fact_update'), write=True),
    tool('lesson', "Write a finding after the person's yes: something learned on a project that will help "
                   "another one, with no customer, person, amount, record or task number in it (refused otherwise: "
                   "rewrite it). tags: what it is about (a topic, a process, a version, an area), as the projects are tagged: "
                   "the pack of a task gives the lessons that share a tag with the task or its project. keywords: "
                   "synonyms, translations and other names, so the search finds it by other words. activities: the "
                   "codes of the work it helps. source_ref (the task) only feeds the leak filter. state active only "
                   "for a lead.",
         {'finding': STRING, 'solution': STRING, 'tags': STRINGS, 'keywords': STRINGS, 'activities': STRINGS,
          'title': STRING, 'applies_to': STRING, 'verified': STRING,
          'state': {'type': 'string', 'enum': ['draft', 'active']}, 'source_ref': STRING, 'generated_by': GENERATED_BY},
         ['finding', 'solution'], route=('memory', 'lesson'), write=True),
    tool('project', "One project: description, milestones (the roadmap), last update (now: its present) and the "
                    "warnings on it. With format okf, as an OKF concept (projects/<id>.md).",
         {'project_id': INTEGER, 'format': FORMAT}, ['project_id'], route=('project', 'project')),
    tool('log', "The history of a project (its updates, the milestones reached) or of a task (its chatter), newest "
                "first, as an OKF log.md.",
         {'project_id': INTEGER, 'task_id': INTEGER, 'limit': INTEGER}, route=('project', 'log')),
    tool('update', "Write a project update after the person's yes, at the end of a session that changed the state of "
                   "the project: title, status, progress (0-100, default the last one) and a plain-text description "
                   "with what changed, the decisions taken, the risks and the next steps against the milestones. It "
                   "becomes the present of the project.",
         {'project_id': INTEGER, 'name': STRING, 'status': {'type': 'string', 'enum': UPDATE_STATUSES},
          'progress': INTEGER, 'description': STRING},
         ['project_id', 'name', 'status', 'description'], route=('project', 'update'), write=True),
    tool('state', "After the person's yes: a lead activates, supersedes or archives a rule or a lesson; the author of a "
                  "fact or a procedure or a lead supersedes or archives it.",
         {'note_id': INTEGER, 'lesson_id': INTEGER, 'fact_id': INTEGER, 'state': {'type': 'string', 'enum': STATES},
          'superseded_by_id': INTEGER}, ['state'], route=('memory', 'state'), write=True),
    tool('log_time', "Hours on a task, as the person gives them (never estimated), with the worklog line as "
                     "description.",
         {'task_id': INTEGER, 'hours': {'type': 'number'}, 'description': STRING, 'date': STRING},
         ['task_id', 'hours', 'description'], route=('timesheet', 'log_time'), write=True),
    tool('review', "My review queue, for the consolidation: draft rules to decide, active rules to re-check, projects "
                   "without a recent update; for a lead also draft lessons and near-duplicate lessons.",
         route=('memory', 'review')),
    tool('confirm', "After re-checking a note with the person: verified today, with an optional expiry (YYYY-MM-DD). "
                    "An active rule only by a lead.",
         {'note_id': INTEGER, 'expires': STRING}, ['note_id'], route=('memory', 'confirm'), write=True),
    tool('documents', "The documents of the memory on a task, project or customer: attachments of that record, files "
                      "or links to an original elsewhere, with their summary. With no anchor, the documents of the "
                      "organisation itself (the company, or company_id).",
         {'task_id': INTEGER, 'project_id': INTEGER, 'partner_id': INTEGER, 'company_id': INTEGER},
         route=('memory', 'document_list')),
    tool('document', "One document of the memory: what and where it is, its summary and, with text true, its text in "
                     "slices (offset, max_chars). With format okf, as an OKF concept (documents/<id>.md).",
         {'document_id': INTEGER, 'text': {'type': 'boolean'}, 'max_chars': INTEGER, 'offset': INTEGER, 'format': FORMAT},
         ['document_id'], route=('memory', 'document_read')),
    tool('document_write', "After the person's yes: bring a document into the memory or read one again. An attachment "
                           "already on a record: document_id (its id), with summary, keywords, read_on, fingerprint "
                           "and the converted text. A new one: name and url (a link to an original elsewhere), one "
                           "anchor (none for a document of the organisation itself). keep_text false for a sensitive "
                           "document.",
         {'document_id': INTEGER, 'name': STRING, 'url': STRING, 'summary': STRING, 'keywords': STRINGS,
          'task_id': INTEGER, 'project_id': INTEGER, 'partner_id': INTEGER, 'company_id': INTEGER,
          'read_on': STRING, 'fingerprint': STRING, 'keep_text': {'type': 'boolean'}, 'text': STRING},
         route=('memory', 'document_write'), write=True),
    tool('document_remove', "Lead only, after the person's yes: take a document out of the memory (what the memory "
                            "brought in goes; an attachment the people put on the record stays).",
         {'document_id': INTEGER}, ['document_id'], route=('memory', 'document_remove'), write=True),
    tool('query', "Read-only question on the ERP as myself: search_read of a model with a domain and fields.",
         {'model': STRING, 'domain': {'type': 'array'}, 'fields': STRINGS, 'limit': INTEGER}, ['model'],
         route=('hub', 'search_read')),
    # the external sources (texo_sources, optional): the triage of Odoo, in the session
    tool('sources_due', "The external source channels overdue (not read for longer than their frequency), with what "
                        "to look for in each and how it is read. The context pack lists them too.",
         {'project_id': INTEGER}, route=('sources', 'due')),
    tool('sources_find', "Search the press review and the other external sources already collected (cards and "
                         "candidates): every word of query, the public persons and themes named, a channel, the period "
                         "of the event, or of publication when the event date is not known (date_from, date_to as YYYY-MM-DD); newest first.",
         {'query': STRING, 'persons': STRINGS, 'themes': STRINGS, 'channel': STRING, 'date_from': STRING,
          'date_to': STRING, 'states': STRINGS, 'limit': INTEGER}, route=('sources', 'find')),
    tool('sources_inbox', "The candidates waiting for the triage, those holding the watched words first, with the "
                          "proposals already made; then the cards to write (to_write): kept and not written yet, or "
                          "sent back by a lead (sent_back), with the notes of their chatter.", {'watched_only': {'type': 'boolean'}, 'limit': INTEGER},
         route=('sources', 'inbox')),
    tool('sources_collect', "On request: read the channels now (by default the overdue ones); new links become "
                            "candidates; the pages to check by hand are listed. Nothing is read on a schedule.",
         {'channel_ids': {'type': 'array', 'items': INTEGER}, 'overdue_only': {'type': 'boolean'}},
         route=('sources', 'collect'), write=True),
    tool('sources_search', "«Search news about X»: what the memory already has on the subject (known), then the "
                           "channels asked now through their search feeds (found; new links become candidates). since "
                           "(YYYY-MM-DD): only what was published from that day (a press review: since the last one). "
                           "Brief entries; read a card in full with read and its concept (sources/12). Then propose a "
                           "triage to the person: for each candidate the action, the theme, the card in short, the "
                           "doubts and the questions.",
         {'query': STRING, 'channel_ids': {'type': 'array', 'items': INTEGER}, 'limit': INTEGER, 'since': STRING},
         ['query'],
         route=('sources', 'search'), write=True),
    tool('sources_link', "A link the person pasted (from a chat, an email) becomes a candidate, on the channel of its "
                         "site; a site the organisation does not follow is refused: propose the channel first.",
         {'url': STRING, 'title': STRING}, ['url'], route=('sources', 'link'), write=True),
    tool('sources_propose', "When the person asked to prepare the triage: keep your proposal on a candidate, so it "
                            "can be decided in Odoo too. action: keep, discard or check; themes; card: the card in "
                            "short; doubts, codes of the fixed list: event_date, private_person, homonym, unconfirmed, "
                            "quote, unreadable, duplicate, partisan, unknown_channel, watch_video; questions: what you "
                            "need to know.",
         {'item_id': INTEGER, 'action': {'type': 'string', 'enum': ['keep', 'discard', 'check']}, 'themes': STRINGS,
          'card': STRING, 'doubts': STRINGS, 'questions': STRING, 'generated_by': GENERATED_BY},
         ['item_id', 'action'], route=('sources', 'propose'), write=True),
    tool('sources_triage', "The person's decision on candidates: keep (with themes and a note), keep_as_proposed, or "
                           "discard.",
         {'item_ids': {'type': 'array', 'items': INTEGER},
          'decision': {'type': 'string', 'enum': ['keep', 'keep_as_proposed', 'discard']}, 'themes': STRINGS,
          'note': STRING}, ['item_ids', 'decision'], route=('sources', 'triage'), write=True),
    tool('sources_card', "After the person's yes: write the card of a candidate. abstract in your words (60-120 words: "
                         "who, what, where, which acts); quotes at most a couple, between «» and attributed: each must be "
                         "in the page word for word, or the card is refused; public persons, bodies, places, themes as "
                         "names; event_date (YYYY-MM-DD) when it happened; stance (positive, neutral, negative, none). A "
                         "card that names persons waits for a lead's approval.",
         {'item_id': INTEGER, 'abstract': STRING, 'quotes': STRING, 'persons': STRINGS, 'bodies': STRINGS,
          'places': STRINGS, 'themes': STRINGS, 'acts': STRING, 'event_date': STRING,
          'stance': {'type': 'string', 'enum': ['positive', 'neutral', 'negative', 'none']},
          'relevance': {'type': 'integer', 'enum': [1, 2, 3]}, 'keywords': STRINGS,
          'related_ids': {'type': 'array', 'items': INTEGER}, 'submit': {'type': 'boolean'}},
         ['item_id', 'abstract'], route=('sources', 'card'), write=True),
    tool('sources_channel', "Lead only, after the person's yes: a new channel to follow (a site the agent met), with "
                            "what to look for, how often (every_days) and its feeds [{kind: rss|video|search|"
                            "search_template|manual, url}] (a search_template has {q} where the subject goes).",
         {'name': STRING, 'website': STRING,
          'kind': {'type': 'string', 'enum': ['press', 'broadcaster', 'video', 'public_body', 'calls', 'legislation',
                                              'other']},
          'look_for': STRING, 'every_days': INTEGER, 'project_id': INTEGER, 'feeds': {'type': 'array'}},
         ['name'], route=('sources', 'channel'), write=True),
]
