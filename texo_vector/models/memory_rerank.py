# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The optional reranker: a cross-encoder reads the question and each of the first results of the
hybrid search together and puts them in a new order.

Off unless an endpoint is configured. Measured on the evaluation sets of the demo customers: it puts the right document first where the hybrid left it
second or third (a design studio: mrr 0.86 to 0.97-1.00) and changes nothing where the hybrid was
right already; on a CPU it costs 7 s (10 results of 800 characters) to 30 s (20 of 2000) per search,
so it is for a machine with an accelerator. When the service does not answer in time the hybrid
order stays, with a warning in the log.

Two services are spoken to: Text Embeddings Inference (POST /rerank, the image of the coordination
stack) and llama.cpp server started with --reranking (POST /v1/rerank), which runs on GPUs that TEI
does not support (AMD and Intel through Vulkan). The texts of the memory go only to a local host,
as for the embeddings, unless texo_vector.allow_remote_endpoint is set."""
import logging
from urllib.parse import urlparse

import requests

from odoo import api, models
from odoo.tools import html2plaintext

from odoo.addons.texo_memory.models.project_task import EPISODE_MESSAGE_TYPES

from .memory_embedding import PARAM_ALLOW_REMOTE

_logger = logging.getLogger(__name__)

PARAM_RERANK_ENDPOINT = 'texo_vector.rerank_endpoint'
PARAM_RERANK_API = 'texo_vector.rerank_api'
PARAM_RERANK_POOL = 'texo_vector.rerank_pool'
PARAM_RERANK_CHARS = 'texo_vector.rerank_chars'
PARAM_RERANK_TIMEOUT = 'texo_vector.rerank_timeout'
PARAM_RERANK_MODEL = 'texo_vector.rerank_model'
APIS = ('tei', 'llamacpp')
DEFAULT_POOL = 10
DEFAULT_CHARS = 800
DEFAULT_TIMEOUT = 5.0


class MemoryEmbedding(models.Model):
    _inherit = 'memory.embedding'

    @api.model
    def _rerank_endpoint(self):
        """The URL of the reranker, or None: not configured, or outside the local network without the opt-in."""
        url = (self._param(PARAM_RERANK_ENDPOINT, 'str', '') or '').strip().rstrip('/')
        if not url:
            return None
        if not self._is_local(urlparse(url).hostname or '') and not self._param(PARAM_ALLOW_REMOTE, 'bool', False):
            _logger.warning("The reranker endpoint %s is not on the local network and %s is not set: the results "
                            "keep the order of the hybrid search.", url, PARAM_ALLOW_REMOTE)
            return None
        return url

    @api.model
    def _rerank_state(self):
        """What a search may expect of the reranker: off (no endpoint named), unavailable (named
        outside the local network without the opt-in: refused), configured (a search decides
        whether it is applied or skipped)."""
        url = (self._param(PARAM_RERANK_ENDPOINT, 'str', '') or '').strip()
        if not url:
            return 'off'
        return 'configured' if self._rerank_endpoint() else 'unavailable'

    @api.model
    def _rerank_pool(self):
        """How many of the first results the reranker reads, 0 when it is off."""
        if not self._rerank_endpoint():
            return 0
        return min(max(self._param(PARAM_RERANK_POOL, 'int', DEFAULT_POOL), 2), 20)

    @api.model
    def _rerank_scores(self, query, texts):
        """[score per text] from the reranker, or None when it is off or does not answer in time."""
        url = self._rerank_endpoint()
        if not url or not texts:
            return None
        api_name = (self._param(PARAM_RERANK_API, 'str', 'tei') or 'tei').strip()
        timeout = self._param(PARAM_RERANK_TIMEOUT, 'float', DEFAULT_TIMEOUT)
        try:
            if api_name == 'llamacpp':
                payload = {'query': query, 'documents': texts, 'top_n': len(texts)}
                model = self._param(PARAM_RERANK_MODEL, 'str', '')
                if model:
                    payload['model'] = model
                answer = requests.post(f"{url}/v1/rerank", json=payload, timeout=timeout)
                answer.raise_for_status()
                items = [(item['index'], item['relevance_score']) for item in answer.json()['results']]
            else:
                answer = requests.post(f"{url}/rerank", json={'query': query, 'texts': texts, 'truncate': True},
                                       timeout=timeout)
                answer.raise_for_status()
                items = [(item['index'], item['score']) for item in answer.json()]
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            _logger.warning("The reranker at %s did not answer in %s s: the results keep the order of the hybrid "
                            "search (%s).", url, timeout, error)
            return None
        scores = [None] * len(texts)
        for index, score in items:
            if 0 <= index < len(texts):
                scores[index] = float(score)
        return None if None in scores else scores


class MemoryNote(models.Model):
    _inherit = 'memory.note'

    @api.model
    def _rerank_text(self, entry, size):
        """What the reranker reads of a result: its title and its text; for a document the passage that
        answered, else its summary; for an episode the description of the task, then the human messages of
        its chatter, newest first: a description is often one line, and the chatter is where the episode
        says what happened (the vectors index each message as a chunk of the task, and the hybrid finds
        the task by it; a reranker that read the description alone would push it down)."""
        if entry.get('lesson'):
            lesson = self.env['memory.lesson'].sudo().browse(entry['id'])
            text = f"{lesson.finding}\n{lesson.solution}"
        elif entry.get('task'):
            messages = self.env['mail.message'].sudo().search_fetch(
                [('model', '=', 'project.task'), ('res_id', '=', entry['id']),
                 ('message_type', 'in', EPISODE_MESSAGE_TYPES)], ['body'], order='id desc')
            text = "\n".join([html2plaintext(self.env['project.task'].sudo().browse(entry['id']).description or ''),
                              *(html2plaintext(message.body or '') for message in messages)])
        elif entry.get('document'):
            passage = entry.get('passage') or {}
            found = self.env['memory.document.passage'].sudo().search(
                [('attachment_id', '=', entry['id']), ('start', '=', passage.get('start'))], limit=1) if passage else None
            text = f"{passage.get('path') or ''}\n{found.text}" if found else (entry.get('summary') or '')
        elif entry.get('source'):
            # a card of the external sources (texo_sources): its id is a card's, never a note's
            Card = self.env['memory.source.item'] if 'memory.source.item' in self.env else None
            card = Card.sudo().browse(entry['id']).exists() if Card is not None else None
            text = "\n".join(filter(None, [card.abstract, card.acts])) if card else (entry.get('snippet') or '')
        elif entry.get('fact') or entry.get('procedure') or entry.get('kind') in ('fact', 'procedure', 'rule'):
            text = self.sudo().browse(entry['id']).body or ''
        else:
            # an entry of a kind this module does not know: what the search already says of it, never the
            # body of a note that happens to have the same id
            text = entry.get('abstract') or entry.get('snippet') or entry.get('summary') or ''
        # sudo: the entries are already the ones the user may read; the text is read to order them
        return f"{entry.get('title') or ''}\n{' '.join(text.split())}"[:size]

    @api.model
    def _reranked(self, query, entries):
        """The entries in the order of the reranker (each with its score as rerank), or as they are."""
        return self._rerank_apply(query, entries)[0]

    @api.model
    def _rerank_apply(self, query, entries):
        """(the entries in the order of the reranker, each with its score as rerank, whether it
        answered); as they are when it did not."""
        Embedding = self.env['memory.embedding']
        if len(entries) < 2:
            return entries, False
        size = min(max(Embedding._param(PARAM_RERANK_CHARS, 'int', DEFAULT_CHARS), 200), 4000)
        scores = Embedding._rerank_scores(query, [self._rerank_text(entry, size) for entry in entries])
        if scores is None:
            return entries, False
        for entry, score in zip(entries, scores, strict=True):
            entry['rerank'] = round(score, 4)
        return sorted(entries, key=lambda entry: -entry['rerank']), True
