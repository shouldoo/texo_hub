# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The vectors of the memory: one table, pgvector, a local embedding service.

What gets a vector: the episodes (a task: its title and description, then each human message of its chatter,
one vector each), the active facts and procedures, the live lessons, the documents (the title,
summary and keywords, then each piece of the converted text, when the document keeps it). Never
the rules: the context pack gives them by chain, a rule is not something to find by meaning.

The vectors are derived data. A write on a record of the scope (a task, a message of its
chatter, a fact, a lesson, a document) marks the record pending (memory.embedding.pending);
a cron, every fifteen minutes, reads the texts of the pending records only, computes the
vectors missing or whose text changed (a hash of the text) and drops those of the chunks gone,
so nothing else in the hub has to know about them and a run costs what changed, not the whole
memory. Where the OCA module queue_job is installed a write also enqueues one job (one at a
time, by identity key) that does the same at once. A weekly reconciliation walks the whole
scope and marks pending what the writes may have missed. The embedding service is Text Embeddings Inference (or any service with its
POST /embed) or llama.cpp server started with --embedding (POST /v1/embeddings, for the AMD and Intel GPUs that
TEI does not support, through Vulkan), reached at a configured endpoint; a host outside the local network is refused
unless the administrator opts in: the texts of the memory never leave the machine by default.

Raw SQL on purpose: the type vector and its operators have no ORM form (memory_note does the
same with tsvector). The ids come from SQL and the records then go through the ORM as the
user, so the access rules apply. Without the extension vector on the database the module
installs, warns, and the search stays lexical.
"""
import hashlib
import ipaddress
import json
import logging
import threading
import time
from urllib.parse import urlparse

import psycopg2
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL, config, html2plaintext, str2bool

from odoo.addons.texo_memory.models import fulltext
from odoo.addons.texo_memory.models.memory_document_passage import PASSAGES_PER_HIT  # noqa: F401
from odoo.addons.texo_memory.models.project_task import EPISODE_MESSAGE_TYPES

_logger = logging.getLogger(__name__)

PARAM_ENDPOINT = 'texo_vector.endpoint'
PARAM_API = 'texo_vector.api'
PARAM_MODEL = 'texo_vector.model'
PARAM_DIMENSIONS = 'texo_vector.dimensions'
PARAM_MODE = 'texo_vector.mode'
PARAM_ALLOW_REMOTE = 'texo_vector.allow_remote_endpoint'
PARAM_DUPLICATE = 'texo_vector.duplicate_similarity'
DEFAULT_MODEL = 'BAAI/bge-m3'
DEFAULT_DIMENSIONS = 1024
DEFAULT_DUPLICATE = 0.80
MODES = ('lexical', 'semantic', 'hybrid')
# the e5 family wants its prefixes on queries and passages; bge-m3 wants none
E5_PREFIXES = {'query': 'query: ', 'passage': 'passage: '}
# texts per call to the service, characters of a text that enter the vector (the service
# truncates to the model's window anyway), vectors computed per cron run
BATCH = 32
MAX_CHARS = 6000
EMBED_LIMIT = 2000
# texts per call inside the cron: smaller calls, so a run stops close to its time; seconds a
# cron run keeps free before it sends a call (it also waits for twice its slowest call so far)
CRON_BATCH = 8
CRON_MARGIN = 30
# seconds a search waits for the vector of its query, seconds the cron waits for a batch
TIMEOUTS = {'query': 10, 'passage': 300}
# the identity key of the job that works off the pending records where queue_job is installed:
# one such job waits at a time, however many writes enqueue it
JOB_IDENTITY = 'texo_vector.embed_pending'
# the nearest chunks read per search: the HNSW index gives at most ef_search rows; the documents
# read more, since the passages of one long act may fill the window (structure.py cuts them)
CANDIDATES = 60
DOCUMENT_CANDIDATES = 200

# the hosts an endpoint may have without the opt-in: the compose network, the machine itself
LOCAL_SUFFIXES = ('.localhost', '.local', '.internal', '.lan')


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


class MemoryEmbeddingPending(models.Model):
    """A record of the scope whose texts changed since its vectors were computed, or that
    entered or left the scope: the cron of the vectors reads these records and no other.
    Written by the hooks of the models of the scope (_touch) and by the reconciliation."""
    _name = 'memory.embedding.pending'
    _description = "Memory Embedding: Pending Record"
    _log_access = False

    res_model = fields.Char(string="Model", required=True, index=True)
    res_id = fields.Integer(string="Record", required=True)

    _unique_record = models.Constraint('UNIQUE(res_model, res_id)', "A record is pending once.")

    @api.model
    def _touch(self, res_model, res_ids):
        """Mark these records pending (once each; a record already pending stays so), then ask
        the queue to work them off now where queue_job is installed."""
        res_ids = [int(res_id) for res_id in res_ids if res_id]
        if not res_ids:
            return
        self.flush_model()
        # raw SQL: an insert that ignores the records already pending, in one statement
        self.env.cr.execute(SQL(
            "INSERT INTO memory_embedding_pending (res_model, res_id) VALUES %s ON CONFLICT DO NOTHING",
            SQL(", ").join(SQL("(%s, %s)", res_model, res_id) for res_id in res_ids)))
        self.invalidate_model()
        self.env['memory.embedding']._schedule_now()

    @api.model
    def _grouped(self):
        """{res_model: [res_id]} of the pending records."""
        groups = {}
        for row in self.sudo().search_fetch([], ['res_model', 'res_id'], order='id'):
            groups.setdefault(row.res_model, []).append(row.res_id)
        return groups

    @api.model
    def _clear(self, keys):
        """The records (res_model, res_id) are up to date: no longer pending."""
        for res_model, res_ids in self._group_keys(keys).items():
            self.sudo().search([('res_model', '=', res_model), ('res_id', 'in', res_ids)]).unlink()

    @staticmethod
    def _group_keys(keys):
        groups = {}
        for res_model, res_id in keys:
            groups.setdefault(res_model, []).append(res_id)
        return groups


class MemoryEmbedding(models.Model):
    """One row per chunk of a record of the memory: the record itself (chunk 0) or one
    message of its chatter (chunk = the message id). The column embedding (type vector)
    is added by init(): pgvector has no ORM field."""
    _name = 'memory.embedding'
    _description = "Memory Embedding"
    _log_access = False
    _rec_name = 'res_model'

    res_model = fields.Char(string="Model", required=True, index=True)
    res_id = fields.Integer(string="Record", required=True)
    chunk = fields.Integer(required=True, default=0,
                           help="0: the record itself; a message id: one message of its chatter.")
    model_name = fields.Char(string="Embedding Model", required=True,
                             help="The model that computed the vector; a change recomputes every vector.")
    text_hash = fields.Char(required=True, help="SHA-256 of the text that was embedded: a change recomputes the vector.")

    _unique_chunk = models.Constraint('UNIQUE(res_model, res_id, chunk)', "One vector per chunk of a record.")

    # -- the schema -----------------------------------------------------------
    def init(self):
        if self._ensure_schema() and not self.search_count([]) and not self.env['memory.embedding.pending'].search_count([]):
            # a database without vectors yet (the install, or a column dropped): every record of the scope waits
            self._mark_all()

    @api.model
    def _param(self, key, type_='str', default=None):
        """A parameter of the configuration, typed (str, int, float, bool); by SQL while the
        registry loads, when init() runs and the other models do not have their methods yet."""
        if self.env.registry.ready:
            Params = self.env['ir.config_parameter'].sudo()
            getters = {'str': Params.get_str, 'int': Params.get_int, 'float': Params.get_float, 'bool': Params.get_bool}
            return getters[type_](key, default)
        self.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (key,))
        row = self.env.cr.fetchone()
        if not row or row[0] in (None, ''):
            return default
        try:
            return {'str': str, 'int': int, 'float': float, 'bool': str2bool}[type_](row[0])
        except ValueError:
            return default

    @api.model
    def _dimensions(self):
        return min(max(self._param(PARAM_DIMENSIONS, 'int', DEFAULT_DIMENSIONS), 1), 4096)

    @api.model
    def _model_name(self):
        return (self._param(PARAM_MODEL, 'str', '') or DEFAULT_MODEL).strip()

    @api.model
    def _column_type(self):
        """The type of the column embedding as PostgreSQL writes it (vector(1024)), or None."""
        self.env.cr.execute(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'memory_embedding'::regclass AND attname = 'embedding' AND NOT attisdropped")
        row = self.env.cr.fetchone()
        return row and row[0]

    @api.model
    def _available(self):
        """Whether the vectors can be stored and searched here: the extension is installed and the
        column exists (dropping the extension drops the column with it)."""
        return bool(self._column_type())

    @api.model
    def _ensure_schema(self):
        """The extension, the column embedding with the configured dimensions and its HNSW index.
        Without the extension (not available, or no privilege to create it) the module stays
        installed and lexical, with a warning. A change of dimensions (another model) drops the
        column and every vector: the cron computes them again."""
        cr = self.env.cr
        cr.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        if not cr.fetchone():
            try:
                with cr.savepoint():
                    cr.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except psycopg2.Error as error:
                _logger.warning("The extension vector is not available on this database (%s): the search stays "
                                "lexical. Install pgvector, then update texo_vector or wait for its cron.",
                                str(error).strip().splitlines()[0])
                return False
        wanted = f"vector({self._dimensions()})"
        current = self._column_type()
        dropped = False
        if current and current != wanted:
            _logger.info("The vectors of the memory change from %s to %s: every vector is computed again.", current, wanted)
            self.invalidate_model()
            cr.execute("DELETE FROM memory_embedding")
            cr.execute("ALTER TABLE memory_embedding DROP COLUMN embedding")
            current, dropped = None, True
        if not current:
            # the dimensions are an integer of this module, never user input
            cr.execute(f"ALTER TABLE memory_embedding ADD COLUMN embedding {wanted}")
        cr.execute("CREATE INDEX IF NOT EXISTS memory_embedding_hnsw_idx ON memory_embedding "
                   "USING hnsw (embedding vector_cosine_ops)")
        if dropped and self.env.registry.ready:
            self._mark_all()
        return True

    # -- the service ----------------------------------------------------------
    @staticmethod
    def _is_local(host):
        """A loopback, private or link-local address; a name without a domain (a compose
        service, the machine itself) or with a local one."""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            host = host.lower()
            return host == 'localhost' or '.' not in host or host.endswith(LOCAL_SUFFIXES)
        return address.is_loopback or address.is_private or address.is_link_local

    @api.model
    def _endpoint(self):
        """The URL of the embedding service, or None: not configured, or outside the local
        network without the opt-in (then a warning says why no vector is computed)."""
        url = (self._param(PARAM_ENDPOINT, 'str', '') or '').strip().rstrip('/')
        if not url:
            return None
        host = urlparse(url).hostname or ''
        if not self._is_local(host) and not self._param(PARAM_ALLOW_REMOTE, 'bool', False):
            _logger.warning("The embedding endpoint %s is not on the local network and %s is not set: no text of the "
                            "memory is sent, no vector is computed.", url, PARAM_ALLOW_REMOTE)
            return None
        return url

    @api.model
    def _prefix(self, kind):
        return E5_PREFIXES[kind] if 'e5' in self._model_name().lower() else ''

    @api.model
    def _embed(self, texts, kind='passage', timeout=None):
        """The vectors of the texts from the service, in batches, or None when the service is
        not configured, not allowed, not reachable or answers with vectors of another size: the
        caller falls back to the lexical search or waits. The API is texo_vector.api: tei (POST
        /embed) or llamacpp (POST /v1/embeddings, the vectors in the order of their index).
        timeout: the seconds a call may take, when shorter than the default of the kind."""
        url = self._endpoint()
        if not url or not texts:
            return None
        prefix, dims, vectors = self._prefix(kind), self._dimensions(), []
        llamacpp = (self._param(PARAM_API, 'str', 'tei') or 'tei').strip() == 'llamacpp'
        try:
            for start in range(0, len(texts), BATCH):
                batch = [prefix + text[:MAX_CHARS] for text in texts[start:start + BATCH]]
                if llamacpp:
                    answer = requests.post(f"{url}/v1/embeddings", timeout=timeout or TIMEOUTS[kind],
                                           json={'input': batch})
                    answer.raise_for_status()
                    vectors += [item['embedding'] for item in sorted(answer.json()['data'], key=lambda i: i['index'])]
                else:
                    answer = requests.post(f"{url}/embed", timeout=timeout or TIMEOUTS[kind],
                                           json={'inputs': batch, 'truncate': True})
                    answer.raise_for_status()
                    vectors += answer.json()
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            _logger.warning("The embedding service at %s did not answer: %s", url, error)
            return None
        if len(vectors) != len(texts) or any(len(vector) != dims for vector in vectors):
            _logger.warning("The embedding service at %s answered with %s vectors of another size than %s: check %s "
                            "and %s.", url, len(vectors), dims, PARAM_MODEL, PARAM_DIMENSIONS)
            return None
        return vectors

    @api.model
    def _embed_query(self, query):
        vectors = self._embed([" ".join((query or '').split())], 'query')
        return vectors and vectors[0]

    @api.model
    def _mode(self, mode=None):
        """The search mode of a call: the one asked, else the configured one; lexical when the
        vectors are not available here."""
        mode = mode or self._param(PARAM_MODE, 'str', '') or 'hybrid'
        if mode not in MODES:
            raise UserError(self.env._("mode is one of %s.", ", ".join(MODES)))
        if mode != 'lexical' and not self._available():
            return 'lexical'
        return mode

    # -- what gets vectors ----------------------------------------------------
    @api.model
    def _sources(self):
        """{res_model: method} of what gets vectors; each method gives
        [(res_model, res_id, chunk, text)], of the records of the ids given, else of every record
        of the scope; a record out of the scope (archived, superseded, without a project) gives
        nothing, whichever way it is asked."""
        return {'project.task': self._texts_of_tasks, 'memory.note': self._texts_of_facts,
                'memory.lesson': self._texts_of_lessons, 'ir.attachment': self._texts_of_documents}

    @staticmethod
    def _of(ids):
        return [('id', 'in', list(ids))] if ids is not None else []

    @api.model
    def _texts_of_tasks(self, ids=None):
        """The episodes: the title, search keywords and description of every task of a project (a task without
        one is a personal to-do), then each human message of its chatter."""
        tasks = self.env['project.task'].sudo().search([('project_id', '!=', False)] + self._of(ids))
        rows = [('project.task', task.id, 0,
                 f"{task.name}\n{task.texo_keywords or ''}\n{html2plaintext(task.description or '')}")
                for task in tasks]
        messages = self.env['mail.message'].sudo().search_fetch(
            [('model', '=', 'project.task'), ('res_id', 'in', tasks.ids), ('message_type', 'in', EPISODE_MESSAGE_TYPES)],
            ['res_id', 'body'], order='id')
        rows += [('project.task', message.res_id, message.id, html2plaintext(message.body or '')) for message in messages]
        return rows

    @api.model
    def _texts_of_facts(self, ids=None):
        """The active facts and procedures: title, keywords, text."""
        notes = self.env['memory.note'].sudo().search(
            [('kind', 'in', ('fact', 'procedure')), ('state', '=', 'active')] + self._of(ids))
        return [('memory.note', note.id, 0, f"{note.name}\n{note.keywords or ''}\n{note.body}") for note in notes]

    @api.model
    def _texts_of_lessons(self, ids=None):
        # the drafts too: the housekeeping looks for the near-duplicates among the drafts and
        # the active ones; the search keeps to the live ones through its domain
        lessons = self.env['memory.lesson'].sudo().search([('state', 'in', ('draft', 'active'))] + self._of(ids))
        return [('memory.lesson', lesson.id, 0, f"{lesson.name}\n{lesson.keywords or ''}\n{lesson.finding}\n{lesson.solution}")
                for lesson in lessons]

    @api.model
    def _texts_of_documents(self, ids=None):
        """The documents of the memory: the title, the summary and the keywords (chunk 0), then
        each passage of the converted text cut by its structure (chunk = the sequence of the
        passage), with the title of the document and the path of the passage before it; a
        sensitive document has no passages and gets its summary only."""
        documents = self.env['ir.attachment'].sudo().search([('texo_document', '=', True)] + self._of(ids))
        rows = [('ir.attachment', document.id, 0,
                 f"{document.name}\n{document.description or ''}\n{document.texo_keywords or ''}")
                for document in documents]
        passages = self.env['memory.document.passage'].sudo().search([('attachment_id', 'in', documents.ids)])
        rows += [('ir.attachment', passage.attachment_id.id, passage.sequence, passage._context())
                 for passage in passages]
        return rows

    @api.model
    def _texts(self, groups=None):
        """{(res_model, res_id, chunk): text} of everything that gets a vector now, whitespace
        folded, the empty ones left out; of the records of groups ({res_model: [res_id]}) only,
        when given."""
        texts = {}
        for res_model, method in self._sources().items():
            if groups is not None and not groups.get(res_model):
                continue
            for res_model, res_id, chunk, text in method(groups.get(res_model) if groups is not None else None):
                text = " ".join((text or '').split())
                if text:
                    texts[(res_model, res_id, chunk)] = text
        return texts

    @api.model
    def _counts(self):
        """{res_model: (chunks with a vector of the current model, records waiting)} of the vectors
        of the memory, from the rows: what a scrape or the state page may ask often."""
        model_name = self._model_name()
        counts = {}
        for res_model, count in self.sudo()._read_group([('model_name', '=', model_name)], ['res_model'], ['__count']):
            counts[res_model] = (count, 0)
        for res_model, count in self.env['memory.embedding.pending'].sudo()._read_group([], ['res_model'], ['__count']):
            stored, _pending = counts.get(res_model, (0, 0))
            counts[res_model] = (stored, count)
        return counts

    @api.model
    def _pending(self):
        """{available, model, stored, pending} of the vectors of the memory: the chunks with a vector
        of the current model, the records waiting for the cron (changed, new, or gone)."""
        result = {'available': self._available(), 'model': self._model_name()}
        if not result['available']:
            return dict(result, stored=0, pending=0)
        counts = self._counts().values()
        return dict(result, stored=sum(c[0] for c in counts), pending=sum(c[1] for c in counts))

    @api.model
    def _mark_all(self):
        """Every record of the scope pending: the install, a change of model or of dimensions, the
        reconciliation when it finds the rows and the scope apart."""
        Pending = self.env['memory.embedding.pending']
        for res_model, method in self._sources().items():
            Pending._touch(res_model, {res_id for _model, res_id, _chunk, _text in method()})

    @api.model
    def _cron_reconcile(self):
        """Weekly: walk the whole scope and mark pending the records whose rows and texts are apart
        (a chunk missing, a text changed, a row of a record gone or out of the scope): what a
        write did not mark, for whatever reason. Nothing is computed here."""
        if not self._available():
            return {'skipped': 'extension'}
        wanted = self._texts()
        model_name = self._model_name()
        rows = self.sudo().search_fetch([], ['res_model', 'res_id', 'chunk', 'model_name', 'text_hash'])
        have = {(row.res_model, row.res_id, row.chunk): row for row in rows}
        apart = {key[:2] for key in have if key not in wanted}
        apart |= {key[:2] for key, text in wanted.items()
                  if key not in have or have[key].model_name != model_name or have[key].text_hash != text_hash(text)}
        Pending = self.env['memory.embedding.pending']
        for res_model, res_ids in Pending._group_keys(apart).items():
            Pending._touch(res_model, res_ids)
        return {'marked': len(apart)}

    @api.model
    def _queue_available(self):
        """Whether the OCA module queue_job is installed here: a write may then enqueue the computation."""
        return 'queue.job' in self.env and hasattr(self, 'with_delay')

    @api.model
    def _schedule_now(self):
        """Ask queue_job, where installed, for one job that works off the pending records now: the
        identity key keeps one such job waiting at a time, however many writes ask. Never raises:
        the cron does the same within fifteen minutes."""
        if not self._queue_available():
            return False
        try:
            self.sudo().with_delay(identity_key=JOB_IDENTITY, description="Memory: vectors of the records changed")\
                ._job_embed()
        except Exception as error:  # noqa: BLE001 - a queue that refuses never fails the write
            _logger.warning("The job of the vectors could not be enqueued (%s): the cron will compute them.", error)
            return False
        return True

    def _job_embed(self):
        """The computation as a job of queue_job: the pending records, in one transaction."""
        return self._cron_embed()

    @api.model
    def _cron_embed(self, limit=EMBED_LIMIT):
        """Compute the vectors of the pending records: those missing, of a changed text or of
        another model, at most limit chunks per run; drop those of the chunks that left the
        scope (a superseded fact, an archived lesson or task, a deleted message). A record
        whose chunks are all stored is no longer pending. {'embedded', 'deleted', 'pending'};
        'skipped' when the vectors cannot be stored here.

        Inside the cron the texts go to the service CRON_BATCH at a time, each batch is
        committed with ir.cron._commit_progress, and a batch is sent only when the time left
        (_cron_time_left) is more than CRON_MARGIN and twice the slowest batch of the run: a
        backlog of hundreds of document pieces (minutes on a CPU) is worked off over several
        runs, and no call is still running when the real-time limit of the cron thread makes
        the server reload. Outside the cron (a shell, a test, a job) the texts go BATCH at a time
        and nothing is committed here."""
        if not self._ensure_schema():
            return {'skipped': 'extension'}
        self.env['mail.message'].flush_model()
        model_name = self._model_name()
        if self.sudo().search_count([('model_name', '!=', model_name)], limit=1):
            # another model: every vector is computed again
            self._mark_all()
        Pending = self.env['memory.embedding.pending']
        groups = Pending._grouped()
        if not groups:
            return {'embedded': 0, 'deleted': 0, 'pending': 0}
        # sudo throughout: the vectors are the module's own rows, of every record of the scope
        # (the search then keeps to what the user may read); the cron runs as root anyway
        wanted = self._texts(groups)
        parts = [['&', ('res_model', '=', res_model), ('res_id', 'in', res_ids)] for res_model, res_ids in groups.items()]
        domain = ['|'] * (len(parts) - 1) + [leaf for part in parts for leaf in part]
        rows = self.sudo().search_fetch(domain, ['res_model', 'res_id', 'chunk', 'model_name', 'text_hash'])
        have = {(row.res_model, row.res_id, row.chunk): row for row in rows}
        gone = self.browse([row.id for key, row in have.items() if key not in wanted])
        gone.sudo().unlink()
        todo = sorted(key for key, text in wanted.items()
                      if key not in have or have[key].model_name != model_name or have[key].text_hash != text_hash(text))
        # the records with nothing to compute are up to date now; a record whose chunks go beyond the
        # limit of this run stays pending for the next one
        records = {(res_model, res_id) for res_model, res_ids in groups.items() for res_id in res_ids}
        deferred = {key[:2] for key in todo[limit:]}
        todo, chunks_pending = todo[:limit], len(todo) - min(len(todo), limit)
        left_of = {}
        for key in todo:
            left_of[key[:2]] = left_of.get(key[:2], 0) + 1
        Pending._clear(records - set(left_of) - deferred)
        if todo and not self._endpoint():
            # no service: nothing can be computed, and a cron that reports work it never does
            # is logged as a warning at every run; the search stays lexical until one is named
            return {'embedded': 0, 'deleted': len(gone), 'pending': len(todo) + chunks_pending, 'skipped': 'endpoint'}
        in_cron = bool(self.env.context.get('cron_id'))
        Cron = self.env['ir.cron']
        left = Cron._commit_progress(remaining=len(todo)) if in_cron else float('inf')
        size = CRON_BATCH if in_cron else BATCH
        embedded, slowest = 0, 0.0
        for start in range(0, len(todo), size):
            timeout = None
            if in_cron:
                left = self._cron_time_left(left)
                if left < max(CRON_MARGIN, 2 * slowest):
                    break  # the time of this run is up: what is stored stays, the next run goes on
                timeout = min(TIMEOUTS['passage'], left - CRON_MARGIN / 2)
            part = todo[start:start + size]
            began = time.monotonic()
            vectors = self._embed([wanted[key] for key in part], 'passage', timeout=timeout)
            if vectors is None:
                break
            slowest = max(slowest, time.monotonic() - began)
            self._store(part, vectors, wanted, have, model_name)
            embedded += len(part)
            done = set()
            for key in part:
                left_of[key[:2]] -= 1
                if left_of[key[:2]] == 0 and key[:2] not in deferred:
                    done.add(key[:2])
            Pending._clear(done)
            if in_cron:
                left = Cron._commit_progress(len(part))
        return {'embedded': embedded, 'deleted': len(gone), 'pending': len(todo) - embedded + chunks_pending}

    @api.model
    def _cron_time_left(self, job_left):
        """The seconds this cron run may still use: job_left, the time Odoo gives the job (what
        ir.cron._commit_progress returns), or less when the real-time limit of the cron thread
        ends first. That limit counts from when the thread entered the database, not from the
        start of the job, and Odoo keeps calling a job that makes progress after its own time
        is up; a thread past the limit makes the whole server reload, every database included.
        The thread's start is the attribute the cron server sets on it (odoo/service/server.py)."""
        limit = config['limit_time_real_cron']
        if limit is None or limit < 0:
            limit = config['limit_time_real']
        started = getattr(threading.current_thread(), 'start_time', None)
        if limit and started:
            job_left = min(job_left, limit - (time.time() - started))
        return job_left

    def _store(self, keys, vectors, wanted, have, model_name):
        """Write the vectors of these chunks: new rows for the new chunks, the model and the
        hash of the text for the others; have is updated with the new rows."""
        new = [key for key in keys if key not in have]
        created = self.sudo().create([{'res_model': m, 'res_id': r, 'chunk': c, 'model_name': model_name,
                                       'text_hash': text_hash(wanted[(m, r, c)])} for m, r, c in new])
        for key, row in zip(new, created, strict=True):
            have[key] = row
        for key in keys:
            if key not in new:
                have[key].sudo().write({'model_name': model_name, 'text_hash': text_hash(wanted[key])})
        self.flush_model()
        self.env.cr.executemany("UPDATE memory_embedding SET embedding = %s::vector WHERE id = %s",
                                [(json.dumps(vector), have[key].id) for key, vector in zip(keys, vectors, strict=True)])

    # -- the search -----------------------------------------------------------
    @api.model
    def _iterative_scan(self):
        """Ask the HNSW index to keep scanning until the limit is met past the filters (pgvector 0.8:
        hnsw.iterative_scan), so the filter on the model and on the readable records does not leave
        the query with fewer candidates than asked. Silently nothing on an older pgvector."""
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        except psycopg2.Error:
            pass

    @api.model
    def _nearest_chunks(self, vector, res_model, limit=CANDIDATES, readable=None):
        """{res_id: (similarity, chunk)} of the records of res_model nearest to the vector, the
        best chunk of each, the nearest first; among the records of readable (the sub-query of
        the ids the user may read, fulltext.readable_ids) when given, else without the access
        rules, which the caller applies."""
        self.flush_model()
        cr = self.env.cr
        literal = json.dumps(vector)
        cr.execute("SET LOCAL hnsw.ef_search = %s", (max(int(limit), 1),))
        self._iterative_scan()
        conditions = [SQL("res_model = %s AND embedding IS NOT NULL", res_model)]
        if readable is not None:
            conditions.append(SQL("res_id IN %s", readable))
        cr.execute(SQL("SELECT res_id, chunk, 1 - (embedding <=> %s::vector) FROM memory_embedding WHERE %s "
                       "ORDER BY embedding <=> %s::vector LIMIT %s",
                       literal, SQL(" AND ").join(conditions), literal, int(limit)))
        best = {}
        for res_id, chunk, similarity in cr.fetchall():
            similarity = round(float(similarity), 4)
            # the relaxed order of the iterative scan may give a worse chunk of a record first
            if res_id not in best or similarity > best[res_id][0]:
                best[res_id] = (similarity, chunk)
        return dict(sorted(best.items(), key=lambda item: -item[1][0]))

    @api.model
    def _nearest_in(self, vector, res_model, res_id, limit=PASSAGES_PER_HIT):
        """The chunks of one record (its passages, chunk 0 left out) nearest to the vector, the nearest
        first: an exact scan of the few hundred rows of the record, not the approximate index."""
        self.flush_model()
        literal = json.dumps(vector)
        # MATERIALIZED: the rows of the record first, then the order; the HNSW index with a filter could
        # return fewer than asked
        self.env.cr.execute(
            "WITH chunks AS MATERIALIZED (SELECT chunk, embedding FROM memory_embedding WHERE res_model = %s "
            "AND res_id = %s AND chunk > 0 AND embedding IS NOT NULL) "
            "SELECT chunk FROM chunks ORDER BY embedding <=> %s::vector LIMIT %s",
            (res_model, int(res_id), literal, int(limit)))
        return [row[0] for row in self.env.cr.fetchall()]

    @api.model
    def _nearest(self, vector, res_model, limit=CANDIDATES):
        """[(res_id, similarity)] of the records of res_model nearest to the vector, as _nearest_chunks."""
        return [(res_id, similarity) for res_id, (similarity, _chunk) in
                self._nearest_chunks(vector, res_model, limit).items()]

    @api.model
    def _readable_chunks(self, vector, res_model, domain, limit, candidates=CANDIDATES):
        """The records of res_model nearest to the vector that the user may read and that match
        the domain, the nearest first, at most limit, with {id: (similarity, best chunk)}. The
        access rules and the domain are in the query (fulltext.readable_ids): the candidates
        are readable records, not the nearest of everyone's; the ORM then reads them as the
        user, the second check."""
        Model = self.env[res_model]
        readable_query = fulltext.readable_ids(Model, domain)
        if readable_query is None:
            return Model.browse(), {}
        nearest = self._nearest_chunks(vector, res_model, candidates, readable_query)
        if not nearest:
            return Model.browse(), nearest
        readable = set(Model.search([('id', 'in', list(nearest))] + list(domain)).ids)
        records = Model.browse([res_id for res_id in nearest if res_id in readable][:limit])
        return records, nearest

    @api.model
    def _readable(self, vector, res_model, domain, limit):
        """The records of res_model nearest to the vector that the user may read and that match
        the domain, the nearest first, at most limit, with {id: similarity}."""
        records, nearest = self._readable_chunks(vector, res_model, domain, limit)
        return records, {res_id: similarity for res_id, (similarity, _chunk) in nearest.items()}

    @api.model
    def _duplicate_pairs(self, res_model, res_ids, similarity):
        """[(first id, second id, similarity)] of the pairs among res_ids whose vectors are at
        least similarity close (cosine), the first id the smaller; and the ids that have a
        vector (the caller compares the others another way)."""
        self.flush_model()
        cr = self.env.cr
        if not res_ids:
            return [], set()
        cr.execute("SELECT res_id FROM memory_embedding WHERE res_model = %s AND res_id IN %s AND embedding IS NOT NULL",
                   (res_model, tuple(res_ids)))
        with_vector = {row[0] for row in cr.fetchall()}
        cr.execute("SELECT a.res_id, b.res_id, 1 - (a.embedding <=> b.embedding) FROM memory_embedding a "
                   "JOIN memory_embedding b ON b.res_model = a.res_model AND b.res_id > a.res_id "
                   "WHERE a.res_model = %s AND a.res_id IN %s AND b.res_id IN %s "
                   "AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL AND (a.embedding <=> b.embedding) <= %s "
                   "ORDER BY a.res_id, b.res_id",
                   (res_model, tuple(res_ids), tuple(res_ids), 1 - float(similarity)))
        return [(a, b, round(float(sim), 4)) for a, b, sim in cr.fetchall()], with_vector
