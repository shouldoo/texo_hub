# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.texo import okf

from .common import CLEAN_FINDING, CLEAN_SOLUTION, MemoryCase, MemoryFixtures


def frontmatter(text):
    """The frontmatter of a concept as a dict: each value is JSON, which is YAML."""
    head, _sep, body = text.partition('\n---\n')
    lines = head.split('\n')
    assert lines[0] == '---', text
    return {key: json.loads(value) for key, value in (line.split(': ', 1) for line in lines[1:])}, body


def files(answer):
    return {f['path']: f['text'] for f in answer['files']}


@tagged('post_install', '-at_install')
class TestOkf(MemoryCase):
    """The memory read back as Open Knowledge Format: every record a concept with its type,
    status, provenance and trust; the pack an index, the updates and the chatter a log."""

    def test_helpers(self):
        self.assertEqual(okf.parse('/facts/12.md'), ('memory.note', 12))
        self.assertEqual(okf.parse('procedures/4'), ('memory.note', 4))
        self.assertEqual(okf.parse('rules/3'), ('memory.note', 3))
        with self.assertRaises(ValueError):
            okf.parse('notes/3')
        self.assertEqual(okf.actor('claude-code/2.1'), 'claude-code/2.1')
        self.assertEqual(okf.actor('human:alice'), 'human:alice')
        self.assertIsNone(okf.actor('just a name'))
        self.assertEqual(okf.description("First one. Second one."), "First one.")
        self.assertEqual(okf.description("1. Check the goods. 2. Book the return."), "1. Check the goods.")
        text = okf.concept({'title': 'A "quoted"\ntitle', 'type': 'Fact', 'tags': [], 'x': None}, 'Body')
        meta, body = frontmatter(text)
        self.assertEqual(meta, {'type': 'Fact', 'title': 'A "quoted"\ntitle'}, "type first, empty keys left out")
        self.assertEqual(body.strip(), 'Body')
        log = okf.log('L', [('2026-10-01', 'Update', 'old'), ('2026-10-30 10:00:00', 'Note', 'new')])
        self.assertLess(log.index('## 2026-10-30'), log.index('## 2026-10-01'), "newest first")

    def test_a_rule_is_a_concept_with_its_trust_and_its_source(self):
        document = self.env['ir.attachment'].browse(self.env['ir.attachment'].with_user(self.lead)._texo_write(
            name='Procedures', url='https://example.com/procedures', project_id=self.project.id,
            summary='The procedures of the warehouse.', fingerprint='a' * 64)['id'])
        written = self.note_as(self.lead, state='active', severity='never', document_id=document.id,
                               generated_by='claude-code/2.1')
        self.assertEqual(written['concept'], f"rules/{written['id']}")
        rule = self.env['memory.note'].browse(written['id'])
        meta, body = frontmatter(rule.with_user(self.member)._okf_concept())
        self.assertEqual((meta['type'], meta['status'], meta['severity']), ('Rule', 'stable', 'never'))
        self.assertEqual(meta['generated']['by'], 'claude-code/2.1')
        self.assertEqual(meta['verified'], {'by': 'human:chm_lead', 'at': f"{fields.Date.today()}T00:00:00Z"})
        self.assertEqual(meta['sources'][0]['resource'], f"/documents/{document.id}.md")
        self.assertEqual(meta['anchor'], f"/projects/{self.project.id}.md")
        self.assertIn('never upgrade', body)
        # a draft of a member: no verification, written by the hub tool when the agent gives no name
        draft = self.env['memory.note'].browse(self.note_as(self.member, generated_by='not an actor')['id'])
        meta, _body = frontmatter(draft._okf_concept())
        self.assertEqual(meta['status'], 'draft')
        self.assertNotIn('verified', meta)
        self.assertTrue(meta['generated']['by'].startswith('texo_memory/'))

    def test_a_fact_cites_its_document_and_goes_stale_when_it_changes(self):
        Attachment = self.env['ir.attachment'].with_user(self.lead)
        document = Attachment.browse(Attachment._texo_write(
            name='Warehouse map', url='https://example.com/map', project_id=self.project.id, fingerprint='a' * 64)['id'])
        written = self.env['memory.note'].with_user(self.member)._agent_note(
            'Warehouse', 'Two locations: the shop and the yard.', project_id=self.project.id, document_id=document.id,
            kind='fact')
        fact = self.env['memory.note'].browse(written['id'])
        self.assertEqual(written['concept'], f"facts/{fact.id}")
        self.assertEqual((fact.origin, fact.verified_by_id, written['document_id']), ('agent', self.member, document.id))
        meta, _body = frontmatter(fact._okf_concept())
        self.assertEqual((meta['type'], meta['verified']['by']), ('Fact', 'human:chm_member'))
        self.assertNotIn('stale', meta)
        # the original changes after the fact was written: to re-check until someone verifies it again
        fact.source_checked = fields.Datetime.now() - timedelta(hours=1)
        Attachment._texo_write(document_id=document.id, fingerprint='b' * 64)
        self.assertEqual(fact._is_stale(fields.Date.today()), 'source_changed')
        meta, _body = frontmatter(fact._okf_concept())
        self.assertEqual(meta['stale'], 'source_changed')
        fact.with_user(self.member)._agent_update(verified=True)
        self.assertIsNone(fact._is_stale(fields.Date.today()))

    def test_a_lesson_is_a_finding_without_its_work(self):
        written = self.env['memory.lesson'].with_user(self.member)._agent_lesson(
            CLEAN_FINDING, CLEAN_SOLUTION, tags=['purchase'], generated_by='codex/1.0')
        lesson = self.env['memory.lesson'].browse(written['id'])
        meta, body = frontmatter(lesson._okf_concept())
        self.assertEqual((meta['type'], meta['status'], meta['tags']), ('Finding', 'draft', ['purchase']))
        self.assertEqual(meta['generated']['by'], 'codex/1.0')
        self.assertNotIn('anchor', meta)
        self.assertIn('# Solution', body)
        # a lesson a person writes in the form names no one, and its day only
        curated = self.env['memory.lesson'].with_user(self.lead).create({
            'name': 'Curated', 'kind': 'lesson', 'finding': CLEAN_FINDING, 'solution': CLEAN_SOLUTION})
        meta, _body = frontmatter(curated._okf_concept())
        self.assertEqual(meta['generated']['by'], 'human:anonymous')
        self.assertTrue(meta['generated']['at'].endswith('T00:00:00Z'))
        self.assertNotIn('chm_lead', curated._okf_concept())

    def test_odoo_itself_is_a_process_not_a_person(self):
        rule = self.env['memory.note'].create({'name': 'Data', 'body': 'From a data file.', 'state': 'active',
                                               'project_id': self.project.id, 'verified': fields.Date.today(),
                                               'verified_by_id': self.env.ref('base.user_root').id})
        meta, _body = frontmatter(rule._okf_concept())
        self.assertEqual((meta['generated']['by'], meta['verified']['by']), ('process:odoo', 'process:odoo'),
                         "machine-confirmed, not human-reviewed")

    def test_the_pack_is_an_index_with_the_binding_rules_and_a_log(self):
        never = self.note_as(self.lead, state='active', severity='never',
                             body='Agents never upgrade a module on production. Ask the person for the stage.')
        short = self.note_as(self.lead, name='Stage', body='Every release goes through the stage.', state='active')
        prefer = self.note_as(self.lead, name='Short answers', body='Prefer short answers.', state='active',
                              severity='prefer')
        fact = self.env['memory.note'].with_user(self.member)._agent_note(
            'Warehouse', 'Two locations: the shop and the yard.', project_id=self.project.id, kind='fact')
        procedure = self.env['memory.note'].with_user(self.member)._agent_note(
            'Receive a return', '1. Check the goods.\n2. Book the return.', project_id=self.project.id, kind='procedure')
        self.env['project.update'].with_user(self.lead).create({
            'project_id': self.project.id, 'name': 'Flows mapped', 'status': 'on_track', 'progress': 40,
            'description': '<p>The returns flow is mapped.</p>'})
        self.task.with_user(self.member)._texo_post_note('Route drafted with the customer.')
        Note = self.env['memory.note'].with_user(self.member)
        pack = Note._agent_context(task_id=self.task.id)
        bundle = files(Note._okf_context(pack, self.task))
        index = bundle['index.md']
        self.assertTrue(index.startswith('---\nokf_version: "0.2"\n---'))
        self.assertIn(f"(/rules/{never['id']}.md) - Rule, never:", index)
        Note.browse(never['id']).sudo().rule_activity_ids = self.env['memory.note.activity'].search([], limit=1)
        index = files(Note._okf_context(Note._agent_context(task_id=self.task.id), self.task))['index.md']
        self.assertRegex(index, rf"\(/rules/{never['id']}\.md\) - Rule, never \(\w+\):", "the activities of the rule")
        self.assertIn(f"(/rules/{prefer['id']}.md) - Rule, prefer:", index)
        self.assertIn(f"(/facts/{fact['id']}.md) - Fact: Two locations", index)
        self.assertIn(f"(/procedures/{procedure['id']}.md) - Procedure: 1. Check the goods.", index)
        meta, _body = frontmatter(self.env['memory.note'].browse(procedure['id'])._okf_concept())
        self.assertEqual(meta['type'], 'Playbook')
        self.assertIn(f"rules/{never['id']}.md", bundle, "a rule that binds comes in full")
        self.assertNotIn(f"rules/{prefer['id']}.md", bundle, "a preference by its title")
        self.assertIn(f"(/rules/{short['id']}.md) - Rule, must: Every release goes through the stage.", index)
        self.assertNotIn(f"rules/{short['id']}.md", bundle, "a short rule is whole in the index")
        self.assertIn(f"tasks/{self.task.id}.md", bundle)
        meta, body = frontmatter(bundle[f"projects/{self.project.id}.md"])
        self.assertEqual(meta['type'], 'Project')
        self.assertEqual(meta['now']['id'], self.project.last_update_id.id)
        self.assertIn('# Now', body)
        self.assertIn('**Update**: Flows mapped (', bundle['log.md'])
        self.assertIn('**Note**: Member: Route drafted with the customer.', bundle['log.md'])


@tagged('post_install', '-at_install')
class TestOkfRoutes(MemoryFixtures, HttpCase):
    """The routes asked in OKF: a concept by its id, the pack as a bundle."""

    def _post(self, route, user, payload):
        key = self.env['res.users.apikeys'].with_user(user)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open(f'/texo/v1/{route}', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    @mute_logger('odoo.http')
    def test_read_a_concept_and_the_pack(self):
        rule = self.note_as(self.lead, state='active')
        answer = self._post('memory/read', self.member, {'concept': f"/rules/{rule['id']}.md", 'format': 'okf'}).json()
        self.assertEqual((answer['format'], answer['okf_version']), ('okf', '0.2'))
        meta, _body = frontmatter(answer['files'][0]['text'])
        self.assertEqual(meta['title'], 'No production')
        self.assertEqual(self._post('memory/read', self.member, {'concept': f"rules/{rule['id']}"}).json()['id'], rule['id'])
        task = self._post('memory/read', self.member, {'concept': f"tasks/{self.task.id}", 'format': 'okf'}).json()
        self.assertEqual([f['path'] for f in task['files']], [f"tasks/{self.task.id}.md", f"tasks/{self.task.id}/log.md"])
        pack = self._post('memory/context', self.member, {'task_id': self.task.id, 'format': 'okf'}).json()
        self.assertEqual(pack['files'][0]['path'], 'index.md')
        log = self._post('project/log', self.member, {'project_id': self.project.id}).json()
        self.assertEqual(log['files'][0]['path'], f"projects/{self.project.id}/log.md")
        self.assertEqual(self._post('memory/read', self.member, {'concept': 'notes/1'}).status_code, 422)
        self.assertEqual(self._post('memory/context', self.member, {'format': 'yaml'}).status_code, 422)
        outsider = self._post('memory/read', self.outsider, {'concept': f"tasks/{self.task.id}", 'format': 'okf'})
        self.assertEqual(outsider.status_code, 404)
