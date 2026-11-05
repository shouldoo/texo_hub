# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The seed of an industry: the activities, sections, rules of the organisation and project
templates a sector brings, applied by an administrator from the hub/seed.toml of the industry.

Every seeded record carries a stable key (industry/kind/code) and the fingerprint of the values
the seed last wrote. A run creates what is missing, updates what nobody changed since, and keeps
what was changed here: the answer lists every item with what happens to it, so the person sees
the differences before applying them (apply false, the default) and after. Nothing is deleted:
an item that left the seed is only reported, and a record with the same code written by hand is
left as it is."""
import hashlib
import json
import re

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext

CODE = re.compile(r'^[a-z][a-z0-9_]*$')
SEVERITIES = ('never', 'must', 'prefer')


def fingerprint(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def plain(html):
    return html2plaintext(html or '').strip()


class MemorySeedMixin(models.AbstractModel):
    _name = 'memory.seed.mixin'
    _description = "Seeded Record"

    seed_key = fields.Char(copy=False, index=True, readonly=True,
                           help="The industry and the key of the seed item this record comes from.")
    seed_fingerprint = fields.Char(copy=False, readonly=True,
                                   help="The values the seed last wrote: a record changed since is kept as it is.")


class MemorySeed(models.AbstractModel):
    _name = 'memory.seed'
    _description = "Industry Seed"

    # -- what each kind of item is, as values to compare and to write ------------
    def _code_values(self, record):
        return {'name': record.name, 'description': (record.description or '').strip(), 'sequence': record.sequence}

    def _code_expected(self, item):
        return {'name': (item.get('name') or '').strip(), 'description': (item.get('description') or '').strip(),
                'sequence': int(item.get('sequence') or 10)}

    def _rule_values(self, record):
        return {'name': record.name, 'body': record.body, 'severity': record.severity, 'state': record.state,
                'activities': sorted(record.rule_activity_ids.mapped('code')),
                'section': record.section_id.code or '', 'keywords': record.keywords or '',
                'applies_to': record.applies_to or ''}

    def _rule_expected(self, item):
        Note = self.env['memory.note']
        activities = item.get('activities') or []
        if isinstance(activities, str):
            activities = activities.split(',')
        return {'name': (item.get('name') or '').strip()[:200], 'body': Note._agent_body(item.get('body')),
                'severity': item.get('severity') or 'must', 'state': 'active',
                'activities': sorted(a.strip() for a in activities if a.strip()),
                'section': item.get('section') or '', 'keywords': Note._agent_keywords(item.get('keywords')) or '',
                'applies_to': item.get('applies_to') or ''}

    def _template_values(self, record):
        tasks = record.with_context(active_test=False).task_ids.sorted(lambda t: (t.sequence, t.id))
        return {'name': record.name, 'description': plain(record.description),
                'tasks': [[task.name, plain(task.description)] for task in tasks]}

    def _template_expected(self, item):
        tasks = item.get('tasks') or []
        return {'name': (item.get('name') or '').strip(), 'description': plain(item.get('description')),
                'tasks': [[(task.get('name') or '').strip(), plain(task.get('description'))] for task in tasks]}

    # -- the run ------------------------------------------------------------------
    @api.model
    def _agent_seed(self, industry, activities=None, sections=None, rules=None, project_templates=None,
                    company_id=None, apply=False, lang='en_US'):
        """Compare the seed of an industry with the hub and, with apply, write the differences.

        industry: the slug of the industry (odoo_partner); every item has a code (activities,
        sections) or a key (rules, project templates), stable across the versions of the seed.
        The rules are rules of the organisation (the company, or company_id), active at once:
        the administrator who applies the seed reviewed them in the answer of the dry run."""
        if self.env.user._texo_check_role() != 'admin':
            raise AccessError(self.env._("Only a Texo administrator applies the seed of an industry."))
        if not CODE.match(industry or ''):
            raise UserError(self.env._("The industry is one lowercase word (letters, digits, underscore): %s.",
                                       industry))
        seed = self.with_context(lang=lang or 'en_US', active_test=False)
        company = seed.env['memory.note']._company(company_id)
        kinds = [
            ('activity', activities, 'code', seed.env['memory.note.activity'], seed._code_values, seed._code_expected,
             []),
            ('section', sections, 'code', seed.env['memory.section'], seed._code_values, seed._code_expected, []),
            ('rule', rules, 'key', seed.env['memory.note'], seed._rule_values, seed._rule_expected,
             [('kind', '=', 'rule'), ('company_id', '=', company.id)]),
            # sudo: a template is configuration of the instance; the administrator of the hub may
            # not be a project manager, and the seed writes only templates it keys
            ('project_template', project_templates, 'key', seed.env['project.project'].sudo(), seed._template_values,
             seed._template_expected, [('is_template', '=', True)]),
        ]
        report = []
        for kind, items, key_field, Model, values, expected, domain in kinds:
            report += seed._seed_kind(industry, kind, items or [], key_field, Model, values, expected, domain,
                                      company, apply)
        counts = {}
        for item in report:
            counts[item['status']] = counts.get(item['status'], 0) + 1
        return {'industry': industry, 'applied': bool(apply), 'counts': counts, 'items': report}

    def _seed_kind(self, industry, kind, items, key_field, Model, values, expected, domain, company, apply):
        prefix = f"{industry}/{kind}/"
        report, seen = [], set()
        for item in items:
            code = (item.get(key_field) or '').strip()
            if not CODE.match(code):
                raise UserError(self.env._("A %(kind)s of the seed needs a %(field)s of one lowercase word: %(code)s.",
                                           kind=kind, field=key_field, code=code))
            if code in seen:
                raise UserError(self.env._("The seed has the %(kind)s %(code)s twice.", kind=kind, code=code))
            seen.add(code)
            want = expected(item)
            record = Model.search(domain + [('seed_key', '=', prefix + code)], limit=1)
            entry = {'kind': kind, 'key': code, 'name': want['name']}
            if not record and key_field == 'code' and Model.search_count([('code', '=', code)]):
                report.append(dict(entry, status='kept', reason='not_from_seed'))
                continue
            if not record:
                entry['status'] = 'created'
                if apply:
                    record = self._seed_write(kind, Model, item, want, company, prefix + code)
            else:
                have = values(record)
                changes = sorted(k for k in want if want[k] != have.get(k))
                if not changes:
                    entry['status'] = 'unchanged'
                    if apply and record.seed_fingerprint != fingerprint(have):
                        record.seed_fingerprint = fingerprint(have)
                elif record.seed_fingerprint == fingerprint(have):
                    entry.update(status='updated', changes=changes)
                    if apply:
                        self._seed_write(kind, Model, item, want, company, prefix + code, record)
                else:
                    entry.update(status='kept', reason='changed_here', changes=changes)
            if record:
                entry['id'] = record.id
            report.append(entry)
        for record in Model.search(domain + [('seed_key', '=like', prefix + '%')]):
            if record.seed_key[len(prefix):] not in seen:
                report.append({'kind': kind, 'key': record.seed_key[len(prefix):], 'name': record.name,
                               'id': record.id, 'status': 'left_seed'})
        return report

    def _seed_write(self, kind, Model, item, want, company, seed_key, record=None):
        if kind in ('activity', 'section'):
            vals = {'name': want['name'], 'description': want['description'] or False, 'sequence': want['sequence']}
            if not record:
                vals['code'] = item['code'].strip()
        elif kind == 'rule':
            if want['severity'] not in SEVERITIES:
                raise UserError(self.env._("The severity of a rule is never, must or prefer."))
            vals = {'kind': 'rule', 'name': want['name'], 'body': want['body'], 'severity': want['severity'],
                    'state': 'active', 'keywords': want['keywords'] or False, 'applies_to': want['applies_to'] or False,
                    'section_id': self.env['memory.section']._from_code(want['section']).id or False,
                    'rule_activity_ids': [Command.set(
                        self.env['memory.note.activity']._from_codes(want['activities']).ids)],
                    'verified': fields.Date.context_today(self), 'verified_by_id': self.env.uid}
            if not record:
                vals.update(self.env['memory.note']._anchor_vals(company_id=company.id))
        else:
            vals = {'name': want['name'], 'description': item.get('description') or False}
            if record:
                record.with_context(active_test=False).task_ids.unlink()
            else:
                vals.update({'is_template': True, 'company_id': company.id})
            vals['task_ids'] = [Command.create({'name': (task.get('name') or '').strip(),
                                                'description': task.get('description') or False,
                                                'sequence': sequence})
                                for sequence, task in enumerate(item.get('tasks') or [], start=1)]
        if record:
            record.write(vals)
        else:
            record = Model.create(dict(vals, seed_key=seed_key))
        record.seed_fingerprint = fingerprint(self._values_of(kind, record))
        return record

    def _values_of(self, kind, record):
        return {'activity': self._code_values, 'section': self._code_values, 'rule': self._rule_values,
                'project_template': self._template_values}[kind](record)
