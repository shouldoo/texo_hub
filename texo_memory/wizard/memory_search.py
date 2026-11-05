# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models

SCOPES = [('all', "All the Memory"), ('rules', "Rules"), ('facts', "Facts"), ('procedures', "Procedures"),
          ('documents', "Documents"), ('lessons', "Lessons"), ('tasks', "Episodes (Tasks)")]
MODES = [('hybrid', "Words and Meaning"), ('lexical', "Words"), ('semantic', "Meaning")]
MATCHES = [('all', "Every Word"), ('some', "Some Words"), ('semantic', "Meaning"), ('both', "Words and Meaning")]
RESULTS = 20


class MemorySearch(models.TransientModel):
    """The search of the agent for the people: the same ranking over the rules, facts,
    procedures, documents and lessons the user may read, or over the episodes, with what
    found each result and the link to its record."""
    _name = 'memory.search'
    _description = "Search the Memory"

    query = fields.Char(string="Question", required=True,
                        help="Words or a question, as you would ask a colleague.")
    scope = fields.Selection(SCOPES, required=True, default='all',
                             help="Episodes are the tasks with their chatter: what happened, not what holds.")
    mode = fields.Selection(MODES, default=lambda self: self._default_mode(),
                            help="Words: the full-text search. Meaning: the vectors, when the hub has them. "
                                 "Both, fused.")
    vectors = fields.Boolean(compute='_compute_vectors', help="Whether the search by meaning is available here.")
    line_ids = fields.One2many('memory.search.line', 'search_id', string="Results", readonly=True)
    searched = fields.Boolean(readonly=True)

    @api.depends('query')
    def _compute_display_name(self):
        for search in self:
            search.display_name = search.query or self.env._("Search the Memory")

    @api.model
    def _default_mode(self):
        """The configured mode; without the vectors, the words."""
        return 'lexical'

    def _compute_vectors(self):
        self.vectors = False

    def action_search(self):
        self.ensure_one()
        entries = self.env['memory.note']._agent_search(self.query, scope=self.scope, limit=RESULTS,
                                                        mode=self.mode or None)
        self.line_ids.unlink()
        self.write({'searched': True, 'line_ids': [
            fields.Command.create(dict(self.env['memory.search.line']._from_entry(entry), sequence=index))
            for index, entry in enumerate(entries)]})


class MemorySearchLine(models.TransientModel):
    _name = 'memory.search.line'
    _description = "Search the Memory: Result"
    _order = 'sequence, id'

    search_id = fields.Many2one('memory.search', required=True, ondelete='cascade')
    sequence = fields.Integer()
    kind = fields.Char()
    title = fields.Char()
    state = fields.Char()
    match = fields.Selection(MATCHES, string="Found By")
    snippet = fields.Char(string="Excerpt")
    path = fields.Char(string="Passage", help="Where in the document the answer stands, e.g. «Art. 43 > comma 2».")
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)

    @api.model
    def _from_entry(self, entry):
        """The line of a search entry: which record, of which kind, found by what."""
        if entry.get('lesson'):
            res_model, kind = 'memory.lesson', self.env._("Lesson")
        elif entry.get('document'):
            res_model, kind = 'ir.attachment', self.env._("Document")
        elif entry.get('task'):
            res_model, kind = 'project.task', self.env._("Episode")
        else:
            res_model = 'memory.note'
            kind = dict(self.env['memory.note']._fields['kind']._description_selection(self.env)).get(entry.get('kind'))
        match = entry.get('match')
        if match in (None, 'lexical'):
            match = entry.get('words')
        state = entry.get('state')
        return {'res_model': res_model, 'res_id': entry['id'], 'kind': kind, 'title': entry.get('title'),
                'state': state if state and state != 'active' else False,
                'match': match if match in dict(MATCHES) else False,
                'snippet': " ".join((entry.get('snippet') or '').split()),
                'path': (entry.get('passage') or {}).get('path') or False}

    def action_open(self):
        self.ensure_one()
        action = {'type': 'ir.actions.act_window', 'res_model': self.res_model, 'res_id': self.res_id,
                  'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current'}
        if self.res_model == 'ir.attachment':
            action['views'] = [(self.env.ref('texo_memory.view_memory_document_form').id, 'form')]
        return action
