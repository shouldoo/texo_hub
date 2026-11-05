# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestDemo(TransactionCase):
    """The demo data, one record per kind of memory, reach the agent: the rule in the rules
    of the session, the fact, the procedure and the documents in the pack of the
    organisation and in the search, the lesson in the search. Only on a database with the
    demo data."""

    def setUp(self):
        super().setUp()
        self.rule = self.env.ref('texo_memory.demo_rule_nessun_invio', raise_if_not_found=False)
        if not self.rule:
            self.skipTest("a database without the demo data")
        self.lead = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Demo Lead', 'login': 'chm_demo_lead',
            'group_ids': [Command.link(self.env.ref('texo.group_texo_lead').id),
                          Command.link(self.env.ref('project.group_project_user').id)]})

    def test_one_record_per_kind_reaches_the_agent(self):
        Note = self.env['memory.note'].with_user(self.lead)
        manual = self.env.ref('texo_memory.demo_document_manuale_comunicazioni')
        procedure = self.env.ref('texo_memory.demo_document_apertura_progetto')
        lesson = self.env.ref('texo_memory.demo_lesson_pdf_scansionato')
        rules = Note._agent_rules_text("Common.", activity='communication')
        self.assertIn("- [never] Nessun invio al cliente senza la persona:", rules['rules'])
        self.assertNotIn(self.rule.id, [r['id'] for r in Note._agent_rules_text("Common.", activity='analysis')['company_rules']],
                         "the rule concerns the communication only")
        self.assertEqual(self.rule.document_id, manual)
        self.assertNotIn('stale', self.rule._agent_summary()[0])
        pack = Note._agent_context()
        fact = self.env.ref('texo_memory.demo_fact_orari')
        self.assertEqual([f['id'] for level in pack['levels'] for f in level.get('facts', [])], [fact.id])
        self.assertEqual([r['id'] for r in Note._agent_search('reperibilità', scope='facts')], [fact.id])
        steps = self.env.ref('texo_memory.demo_procedure_apertura')
        self.assertEqual([p['id'] for level in pack['levels'] for p in level.get('procedures', [])], [steps.id])
        self.assertEqual((steps.document_id, steps.section_id.code), (procedure, 'operations'),
                         "a procedure taken from the document that stays its source")
        documents = [d['id'] for level in pack['levels'] for d in level.get('documents', [])]
        self.assertEqual(documents, [manual.id, procedure.id])
        manual = manual.with_user(self.lead)
        self.assertTrue(manual._texo_summary()[0]['has_text'])
        self.assertIn("Tono", manual._texo_read(text=True)['text'])
        # a word with an accent, only in the text of the manual
        self.assertEqual([r['id'] for r in Note._agent_search('può', scope='documents')], [manual.id])
        self.assertEqual([r['id'] for r in Note._agent_search('milestone', scope='documents')], [procedure.id])
        self.assertEqual([r['id'] for r in Note._agent_search('scansionato OCR', scope='lessons')], [lesson.id])
