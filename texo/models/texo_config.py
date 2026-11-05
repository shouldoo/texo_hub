# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The configuration of the organisation for the texo CLI: the skill packs it installs, at which version, and
the threads (sources, tools, connectors) it mounts next to the memory.

The CLI reads it with the route config (every role) and mounts it on the person's machine; an administrator
writes it with admin/config, a dry run first. A credential is never stored here: a thread names it as env:NAME
and the person keeps its value in ~/.config/texo/<organisation>.env.
"""
import json
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

SLUG = re.compile(r'^[a-z][a-z0-9_]*$')
THREAD_ID = re.compile(r'^[a-z][a-z0-9_-]*$')
VERSION = re.compile(r'^v?\d+(\.\d+){0,3}$')
CREDENTIAL_NAME = re.compile(r'(?i)token|key|secret|password')
# the fields of a thread that are columns; every other key of a declaration goes in settings
THREAD_COLUMNS = ('id', 'type', 'driver', 'data_class', 'writes', 'guide')
TYPES = [('source', "Source"), ('tool', "Tool"), ('connector', "Connector")]
DRIVERS = [('git-remote', "git-remote"), ('git-mirror', "git-mirror"), ('http', "http"),
           ('mcp-stdio', "mcp-stdio"), ('mcp-http', "mcp-http"), ('cli', "cli")]
DATA_CLASSES = [('public', "Public"), ('org', "Organisation"), ('customer', "Customer")]
WRITES = [('never', "Never"), ('confirm', "After confirmation")]


def slugify(text):
    slug = re.sub(r'[^a-z0-9]+', '_', (text or '').lower()).strip('_')
    return slug if slug and slug[0].isalpha() else f'org_{slug}'.rstrip('_')


class ResCompany(models.Model):
    _inherit = 'res.company'

    texo_slug = fields.Char(
        string="Texo Slug",
        help="The name of the organisation for the texo CLI: its credentials file is ~/.config/texo/<slug>.env. "
             "Empty: derived from the name of the company.")

    @api.constrains('texo_slug')
    def _check_texo_slug(self):
        for company in self:
            if company.texo_slug and not SLUG.match(company.texo_slug):
                raise UserError(self.env._(
                    "The Texo slug is one lowercase word (letters, digits, underscore): %s.", company.texo_slug))

    def _texo_slug(self):
        self.ensure_one()
        return self.texo_slug or slugify(self.name)


class TexoPack(models.Model):
    """A skill pack of the marketplace the organisation installs, at a version."""
    _name = 'texo.pack'
    _description = "Texo Skill Pack"
    _order = 'name'

    name = fields.Char(required=True, help="The pack of the marketplace, e.g. odoo_partner.")
    version = fields.Char(required=True, help="The version the organisation installs, e.g. v1.0.0.")
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company,
                                 ondelete='cascade')
    active = fields.Boolean(default=True)

    _name_company_unique = models.Constraint('UNIQUE(company_id, name)', "A pack is installed once per company.")

    @api.constrains('name', 'version')
    def _check_pack(self):
        for pack in self:
            if not SLUG.match(pack.name or ''):
                raise UserError(self.env._("A pack is named by one lowercase word: %s.", pack.name))
            if not VERSION.match(pack.version or ''):
                raise UserError(self.env._("The version of a pack is a tag such as v1.2.0: %s.", pack.version))

    def _agent_summary(self):
        return [{'name': pack.name, 'version': pack.version} for pack in self]


class TexoThread(models.Model):
    """A thread the organisation mounts next to the memory: what it is, what it may receive, how it connects.
    The settings of its driver (repository, ref, URL, command…) are a JSON object; a credential only as env:NAME."""
    _name = 'texo.thread'
    _description = "Texo Thread"
    _order = 'code'

    code = fields.Char(string="Thread", required=True, help="The id of the thread, e.g. normativa.")
    thread_type = fields.Selection(TYPES, string="Type", required=True)
    driver = fields.Selection(DRIVERS, required=True)
    data_class = fields.Selection(DATA_CLASSES, required=True,
                                  help="What the thread may receive: never data of a class above its own.")
    writes = fields.Selection(WRITES, required=True, default='never')
    guide = fields.Text(help="When the agent uses it, and its limits.")
    settings = fields.Text(default='{}', help="The settings of the driver, as a JSON object: repo, ref, url, "
                                             "paths, skills, command, args, env, auth…")
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company,
                                 ondelete='cascade')
    active = fields.Boolean(default=True)

    _code_company_unique = models.Constraint('UNIQUE(company_id, code)', "A thread id is used once per company.")

    @api.constrains('code', 'thread_type', 'data_class', 'writes', 'settings')
    def _check_thread(self):
        for thread in self:
            if not THREAD_ID.match(thread.code or '') or thread.code == 'memoria':
                raise UserError(self.env._(
                    "A thread id is one lowercase word (letters, digits, - or _), and memoria is the hub: %s.",
                    thread.code))
            if thread.thread_type == 'source' and thread.writes != 'never':
                raise UserError(self.env._("A source is read only: %s.", thread.code))
            if thread.thread_type == 'connector' and thread.data_class == 'public':
                raise UserError(self.env._(
                    "A connector holds data of the organisation or its customers, never public: %s.", thread.code))
            thread._settings_dict()

    def _settings_dict(self):
        """The settings as a dict; a credential written as its value is refused, so none is ever stored."""
        self.ensure_one()
        try:
            settings = json.loads(self.settings or '{}')
        except ValueError:
            raise UserError(self.env._("The settings of %s are not a JSON object.", self.code)) from None
        if not isinstance(settings, dict):
            raise UserError(self.env._("The settings of %s are not a JSON object.", self.code))
        clash = sorted(set(settings) & set(THREAD_COLUMNS))
        if clash:
            raise UserError(self.env._("The settings of %(code)s repeat %(keys)s.", code=self.code,
                                       keys=", ".join(clash)))
        credentials = [str(settings.get(key)) for key in ('auth', 'token') if settings.get(key)]
        credentials += [str(value) for name, value in (settings.get('env') or {}).items()
                        if CREDENTIAL_NAME.search(name)]
        if any(not value.startswith('env:') for value in credentials):
            raise UserError(self.env._(
                "A credential of %s is written as env:NAME, never as its value: nothing is stored.", self.code))
        return settings

    def _agent_declaration(self):
        """The thread as a [[thread]] of texo.toml."""
        self.ensure_one()
        declaration = {'id': self.code, 'type': self.thread_type, 'driver': self.driver,
                       'data_class': self.data_class, 'writes': self.writes}
        if self.guide:
            declaration['guide'] = self.guide
        declaration.update(self._settings_dict())
        return declaration


class TexoConfig(models.AbstractModel):
    """The configuration of an organisation as the CLI reads and an administrator writes it."""
    _name = 'texo.config'
    _description = "Texo Configuration"

    @api.model
    def _company(self, company_id=None):
        if not company_id:
            return self.env.company
        company = self.env['res.company'].browse(int(company_id)).exists()
        if not company or company not in self.env.user.company_ids:
            raise UserError(self.env._("Company %s does not exist or is not yours.", company_id))
        return company

    @api.model
    def _agent_config(self, company_id=None):
        """What the CLI mounts: the organisation, its packs and its threads."""
        self.env.user._texo_check_role()
        company = self._company(company_id)
        domain = [('company_id', '=', company.id)]
        return {
            'organisation': company._texo_slug(), 'company': company.name,
            'packs': self.env['texo.pack'].search(domain)._agent_summary(),
            'threads': [thread._agent_declaration() for thread in self.env['texo.thread'].search(domain)],
        }

    @api.model
    def _agent_set_config(self, packs=None, threads=None, slug=None, company_id=None, apply=False):
        """Make the configuration say what the payload says: the packs and threads given are created or
        updated, those of the company not given are archived (never deleted), the slug set when given. A list
        left out (None) is not touched. Without apply nothing is written: the answer lists the differences."""
        if self.env.user._texo_check_role() != 'admin':
            raise AccessError(self.env._("Only a Texo administrator changes the configuration of the organisation."))
        company = self._company(company_id)
        items = []
        with self.env.cr.savepoint() as savepoint:
            if slug is not None and slug != company._texo_slug():
                company.texo_slug = slug
                items.append({'kind': 'organisation', 'key': slug, 'status': 'updated'})
            if packs is not None:
                items += self._sync(company, 'texo.pack', 'name', packs, self._pack_vals)
            if threads is not None:
                items += self._sync(company, 'texo.thread', 'code', threads, self._thread_vals)
            if not apply:
                # the constraints ran on the writes: a dry run refuses what apply would refuse
                self.env.flush_all()
                savepoint.rollback()
        if not apply:
            self.env.invalidate_all()
        counts = {}
        for item in items:
            counts[item['status']] = counts.get(item['status'], 0) + 1
        return {'applied': bool(apply), 'counts': counts, 'items': items}

    def _pack_vals(self, item):
        return {'name': (item.get('name') or '').strip(), 'version': (item.get('version') or '').strip()}

    def _thread_vals(self, item):
        settings = {key: value for key, value in item.items() if key not in THREAD_COLUMNS}
        return {'code': (item.get('id') or '').strip(), 'thread_type': item.get('type'), 'driver': item.get('driver'),
                'data_class': item.get('data_class'), 'writes': item.get('writes') or 'never',
                'guide': item.get('guide') or False, 'settings': json.dumps(settings, sort_keys=True)}

    def _sync(self, company, model, key, wanted, vals_of):
        Model = self.env[model].with_context(active_test=False)
        existing = {record[key]: record for record in Model.search([('company_id', '=', company.id)])}
        kind = model.split('.')[1]
        items, seen = [], set()
        for item in wanted:
            vals = vals_of(item)
            name = vals[key]
            if name in seen:
                raise UserError(self.env._("The configuration has the %(kind)s %(name)s twice.", kind=kind, name=name))
            seen.add(name)
            record = existing.get(name)
            if not record:
                Model.create(dict(vals, company_id=company.id))
                items.append({'kind': kind, 'key': name, 'status': 'created'})
                continue
            changes = sorted(field for field, value in vals.items() if record[field] != (value or False)
                             and not (field == 'settings' and json.loads(record.settings or '{}') == json.loads(value)))
            if changes or not record.active:
                record.write(dict(vals, active=True))
                items.append({'kind': kind, 'key': name, 'status': 'updated', 'changes': changes or ['active']})
            else:
                items.append({'kind': kind, 'key': name, 'status': 'unchanged'})
        for name, record in existing.items():
            if name not in seen and record.active:
                record.active = False
                items.append({'kind': kind, 'key': name, 'status': 'archived'})
        return items
