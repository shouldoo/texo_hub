# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Generic read-only access for agents, behind the Texo token.

The agent writes its own queries (model, domain, fields), like it would on
/json/2, but:
  * everything runs as the calling user: ACLs and record rules apply;
  * the routes are read-only (read-only cursor), so nothing can be written;
  * technical and security models are refused, sensitive and binary fields
    are never returned, and results are capped and flattened for an LLM.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_GROUPS = 200
MAX_TEXT = 2000
MAX_IDS = 20

BLOCKED_MODEL_PREFIXES = (
    'ir.', 'base.', 'bus.', 'iap.', 'auth.', 'auth_', 'res.config',
    'res.users.apikeys', 'res.users.identitycheck', 'res.users.log',
    'res.users.settings', 'res.device', 'mail.alias',
)
# Field names that look like credentials, matched on whole underscore-separated words.
SENSITIVE_FIELD = re.compile(
    r'(^|_)(password|passwd|pass|secret|secrets|token|tokens|apikey|key|keys|hmac|'
    r'signature|salt|otp|totp|pin|credential|credentials|private)(_|$)'
)
BLOCKED_FIELD_TYPES = ('binary',)
DOMAIN_OPERATORS = ('&', '|', '!')


class TexoApi(models.AbstractModel):
    _name = 'texo.api'
    _description = "Texo Agent API"

    # -- checks ---------------------------------------------------------------
    @api.model
    def _blocked_model(self, model_name):
        return model_name.startswith(BLOCKED_MODEL_PREFIXES)

    @api.model
    def _get_model(self, model_name):
        if not isinstance(model_name, str) or model_name not in self.env:
            raise UserError(_("Unknown model: %(model)s", model=model_name))
        Model = self.env[model_name]
        if Model._abstract or Model._transient or self._blocked_model(model_name):
            raise AccessError(_("Model %(model)s is not available to agents.", model=model_name))
        Model.check_access('read')
        return Model

    @api.model
    def _readable_fields(self, Model):
        """Fields the user can read, minus binary and credential-like ones."""
        described = Model.fields_get(attributes=['type', 'string', 'relation'])
        return {
            name: desc for name, desc in described.items()
            if desc['type'] not in BLOCKED_FIELD_TYPES and not SENSITIVE_FIELD.search(name)
        }

    @api.model
    def _check_fields(self, Model, names, readable):
        names = list(names or [])
        refused = [name for name in names if name.split(':')[0] not in readable]
        if refused:
            raise UserError(_(
                "Fields not available on %(model)s: %(fields)s. Use the fields route to list them.",
                model=Model._name, fields=", ".join(refused)))
        return names

    @api.model
    def _check_domain(self, domain):
        if domain is None:
            return []
        if not isinstance(domain, list):
            raise UserError(_("The domain must be a list."))
        for leaf in domain:
            if isinstance(leaf, str) and leaf in DOMAIN_OPERATORS:
                continue
            if not (isinstance(leaf, (list, tuple)) and len(leaf) == 3 and isinstance(leaf[0], str)):
                raise UserError(_("Invalid domain element: %(leaf)s", leaf=leaf))
            if any(SENSITIVE_FIELD.search(part) for part in leaf[0].split('.')):
                raise AccessError(_("The domain uses a field that is not available to agents."))
        return domain

    # -- formatting -----------------------------------------------------------
    @api.model
    def _flatten(self, value, field_type):
        if value is False or value is None:
            return None
        if field_type == 'html':
            return self._truncate(html2plaintext(value or ''))
        if field_type in ('char', 'text'):
            return self._truncate(value)
        if field_type == 'date':
            return fields.Date.to_string(value)
        if field_type == 'datetime':
            return fields.Datetime.to_string(value)
        if field_type in ('one2many', 'many2many') and isinstance(value, list):
            if len(value) > MAX_IDS:
                return {'ids': value[:MAX_IDS], 'count': len(value)}
            return value
        if isinstance(value, tuple):
            return list(value)
        return value

    @api.model
    def _truncate(self, text):
        text = (text or '').strip()
        return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + " [...]"

    # -- operations -----------------------------------------------------------
    @api.model
    def _agent_search_read(self, model, domain=None, fields=None, limit=None, offset=0, order=None):
        Model = self._get_model(model)
        readable = self._readable_fields(Model)
        names = self._check_fields(Model, fields or ['display_name'], readable)
        domain = self._check_domain(domain)
        limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
        rows = Model.search_read(domain, names, offset=int(offset or 0), limit=limit + 1, order=order)
        has_more = len(rows) > limit
        types = {name: readable[name]['type'] for name in names}
        records = [
            {'id': row['id'], **{name: self._flatten(row.get(name), types[name]) for name in names}}
            for row in rows[:limit]
        ]
        return {'model': model, 'count': len(records), 'has_more': has_more, 'records': records}

    @api.model
    def _agent_read_group(self, model, domain=None, groupby=None, aggregates=None, limit=None, order=None):
        Model = self._get_model(model)
        readable = self._readable_fields(Model)
        groupby = self._check_fields(Model, groupby, readable)
        aggregates = list(aggregates or ['__count'])
        self._check_fields(Model, [a for a in aggregates if a != '__count'], readable)
        domain = self._check_domain(domain)
        limit = max(1, min(int(limit or 50), MAX_GROUPS))
        groups = Model.formatted_read_group(domain, groupby, aggregates, limit=limit + 1, order=order)
        has_more = len(groups) > limit
        return {
            'model': model,
            'has_more': has_more,
            'groups': [
                {key: list(value) if isinstance(value, tuple) else value
                 for key, value in group.items() if key != '__extra_domain'}
                for group in groups[:limit]
            ],
        }

    @api.model
    def _agent_fields(self, model, query=None):
        Model = self._get_model(model)
        query = (query or '').lower()
        result = [
            {'name': name, 'type': desc['type'], 'label': desc['string'],
             **({'relation': desc['relation']} if desc.get('relation') else {})}
            for name, desc in sorted(self._readable_fields(Model).items())
            if not query or query in name or query in (desc['string'] or '').lower()
        ]
        return {'model': model, 'fields': result}

    @api.model
    def _agent_models(self, query):
        if not query or len(query) < 3:
            raise UserError(_("Give at least 3 characters to search models."))
        # sudo: ir.model is not readable by regular users; only names are listed,
        # and each model is then checked for read access as the user below.
        candidates = self.env['ir.model'].sudo().search(
            [('transient', '=', False), '|', ('model', 'ilike', query), ('name', 'ilike', query)], limit=100)
        result = []
        for ir_model in candidates:
            name = ir_model.model
            if name not in self.env or self._blocked_model(name) or self.env[name]._abstract:
                continue
            if self.env[name].has_access('read'):
                result.append({'model': name, 'label': ir_model.name})
        return {'models': result[:50]}
