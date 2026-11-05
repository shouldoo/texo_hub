# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, models

from odoo.addons.texo_memory.models.memory_lesson import DUPLICATE_SIMILARITY

from .memory_embedding import DEFAULT_DUPLICATE, PARAM_DUPLICATE


class MemoryLesson(models.Model):
    _inherit = 'memory.lesson'

    @api.model
    def _duplicate_pairs(self, similarity=DUPLICATE_SIMILARITY, lessons=None):
        """The near-duplicates by meaning: two live lessons about the same thing (a tag in
        common, or both without tags) whose vectors are at least the configured cosine
        similarity close, where difflib sees two different texts. The lessons without a
        vector yet (or every one, without the extension) are compared by difflib as before.
        The ratio given is the similarity in percent; older lesson first."""
        Embedding = self.env['memory.embedding']
        lessons = lessons if lessons is not None else self.search([('state', 'in', ('draft', 'active'))], order='id')
        if not Embedding._available() or not lessons:
            return super()._duplicate_pairs(similarity, lessons)
        threshold = Embedding._param(PARAM_DUPLICATE, 'float', DEFAULT_DUPLICATE)
        close, with_vector = Embedding._duplicate_pairs('memory.lesson', lessons.ids, threshold)
        by_id = {lesson.id: lesson for lesson in lessons}
        pairs = []
        for first_id, second_id, cosine in close:
            first, second = by_id[first_id], by_id[second_id]
            if (first.tag_ids or second.tag_ids) and not first.tag_ids & second.tag_ids:
                continue
            pairs.append((first, second, int(cosine * 100)))
        if with_vector < set(lessons.ids):
            # a lesson without a vector yet is compared with every other by its text
            pairs += [pair for pair in super()._duplicate_pairs(similarity, lessons)
                      if pair[0].id not in with_vector or pair[1].id not in with_vector]
        return sorted(pairs, key=lambda pair: (pair[0].id, pair[1].id))
