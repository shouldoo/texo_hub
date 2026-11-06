# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import fields, models

from .memory_embedding import PARAM_ENDPOINT


class MemoryVectorStatus(models.TransientModel):
    """The state of the search by meaning, for the administrators: the embedding model and
    service, how many texts have their vector and how many wait for it, by kind, and when
    the vectors were last computed. A backlog that does not shrink is a service that does
    not answer or a cron that does not run."""
    _name = 'memory.vector.status'
    _description = "Memory: State of the Search"

    available = fields.Boolean(string="Vectors Available", readonly=True,
                               help="The pgvector extension and the column of the vectors exist in this database.")
    mode = fields.Char(string="Search Mode", readonly=True)
    model_name = fields.Char(string="Embedding Model", readonly=True)
    endpoint = fields.Char(string="Embedding Service", readonly=True)
    rerank = fields.Char(string="Reranker", readonly=True,
                         help="The service that reorders the first results of the hybrid search, if any.")
    last_run = fields.Datetime(string="Last Computed", readonly=True)
    next_run = fields.Datetime(string="Next Computation", readonly=True)
    cron_active = fields.Boolean(string="Scheduled", readonly=True)
    texts = fields.Integer(readonly=True, help="The chunks with a vector plus the records waiting.")
    stored = fields.Integer(string="With a Vector", readonly=True, help="Chunks with a vector of the current model.")
    pending = fields.Integer(string="Waiting", readonly=True,
                             help="Records changed, new or gone since their vectors were computed: the cron "
                                  "reads them at its next run.")
    line_ids = fields.One2many('memory.vector.status.line', 'status_id', readonly=True)

    def _compute_display_name(self):
        self.display_name = self.env._("State of the Search")

    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        values.update({name: value for name, value in self._measure().items() if name in fields_list})
        return values

    def _measure(self):
        """What the vectors are now: the texts of the scope against the stored rows, as the cron compares them."""
        Embedding = self.env['memory.embedding'].sudo()
        cron = self.env.ref('texo_vector.ir_cron_memory_vectors', raise_if_not_found=False)
        result = {'available': Embedding._available(), 'mode': Embedding._mode(), 'model_name': Embedding._model_name(),
                  'endpoint': Embedding._param(PARAM_ENDPOINT, 'str', '') or False,
                  'rerank': (self.env._("%(url)s, first %(pool)s results", url=Embedding._rerank_endpoint(),
                                        pool=Embedding._rerank_pool())
                             if Embedding._rerank_endpoint() else self.env._("Off")),
                  'last_run': cron.sudo().lastcall if cron else False,
                  'next_run': cron.sudo().nextcall if cron else False, 'cron_active': bool(cron and cron.sudo().active)}
        if not result['available']:
            return result
        by_model = Embedding._counts()
        labels = {'project.task': self.env._("Episodes (Tasks)"), 'memory.note': self.env._("Facts and Procedures"),
                  'memory.lesson': self.env._("Lessons"), 'ir.attachment': self.env._("Documents")}
        # stored: the chunks with a vector of the current model; pending: the records waiting for the cron
        lines = [fields.Command.create({'res_model': res_model, 'label': labels.get(res_model, res_model),
                                        'texts': stored + pending, 'stored': stored, 'pending': pending})
                 for res_model, (stored, pending) in sorted(by_model.items())]
        stored = sum(counts[0] for counts in by_model.values())
        pending = sum(counts[1] for counts in by_model.values())
        return dict(result, texts=stored + pending, stored=stored, pending=pending, line_ids=lines)

    def action_compute_now(self):
        """Ask the cron of the vectors to run as soon as a worker is free: the computation takes minutes on a
        CPU and is not done in the request of the page."""
        self.env.ref('texo_vector.ir_cron_memory_vectors').sudo()._trigger()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'info', 'message': self.env._(
                    "The vectors will be computed in the background; refresh this page in a few minutes.")}}

    def action_refresh(self):
        return self.env['ir.actions.act_window']._for_xml_id('texo_vector.action_memory_vector_status')


class MemoryVectorStatusLine(models.TransientModel):
    _name = 'memory.vector.status.line'
    _description = "Memory: State of the Search by Kind"

    status_id = fields.Many2one('memory.vector.status', required=True, ondelete='cascade')
    res_model = fields.Char(readonly=True)
    label = fields.Char(string="Kind", readonly=True)
    texts = fields.Integer(readonly=True)
    stored = fields.Integer(string="With a Vector", readonly=True)
    pending = fields.Integer(string="Waiting", readonly=True)
