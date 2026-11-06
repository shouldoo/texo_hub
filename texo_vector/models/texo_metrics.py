# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, models

from .memory_embedding import PARAM_ENDPOINT


class TexoMetrics(models.AbstractModel):
    _inherit = 'texo.metrics'

    @api.model
    def _collect(self):
        """The vectors: whether they are available, the services named, the texts of each kind with
        and without their vector, and when the cron last computed them. A backlog that does not
        shrink between two scrapes is a service that does not answer or a cron that does not run."""
        metrics = super()._collect()
        Embedding = self.env['memory.embedding'].sudo()
        available = Embedding._available()
        metrics.append(self._metric('texo_vector_available', "The extension vector and the column exist here.",
                                    available))
        metrics.append(self._metric('texo_vector_endpoint_configured', "An embedding service is named and allowed.",
                                    bool(Embedding._endpoint())))
        metrics.append(self._metric('texo_vector_rerank_configured', "A reranker is named and allowed.",
                                    bool(Embedding._rerank_endpoint())))
        metrics.append(self._metric('texo_vector_info', "The embedding model and mode.", 1,
                                    {'model': Embedding._model_name(), 'mode': Embedding._mode(),
                                     'endpoint': 'set' if Embedding._param(PARAM_ENDPOINT, 'str', '') else 'none'}))
        if available:
            for res_model, (texts, stored) in sorted(Embedding._counts().items()):
                labels = {'model': res_model}
                metrics.append(self._metric('texo_vector_texts', "Texts of the scope, by kind.", texts, labels))
                metrics.append(self._metric('texo_vector_stored', "Texts with a current vector, by kind.", stored, labels))
                metrics.append(self._metric('texo_vector_pending', "Texts waiting for their vector, by kind.",
                                            texts - stored, labels))
        cron = self.env.ref('texo_vector.ir_cron_memory_vectors', raise_if_not_found=False)
        if cron:
            cron = cron.sudo()
            metrics.append(self._metric('texo_vector_cron_active', "The cron of the vectors is scheduled.",
                                        bool(cron.active)))
            if cron.lastcall:
                metrics.append(self._metric('texo_vector_cron_lastcall_seconds',
                                            "When the cron of the vectors last ran, as a Unix time.",
                                            int(cron.lastcall.timestamp())))
        return metrics
