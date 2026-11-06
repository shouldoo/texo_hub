# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The metrics of the hub, for a scraper (Prometheus exposition format, text).

One abstract model every module of the hub extends: each adds the gauges of what it keeps (the notes by
kind and state, the vectors waiting, the cron of the vectors). The route /texo/metrics renders them for an
administrator's token; nothing here is written, and no text of the memory leaves: counts and timestamps only.
"""
from odoo import api, models

from .res_users import HUB_ROLE_GROUPS


def render(metrics):
    """The exposition text of [{name, help, type, labels, value}]: HELP and TYPE once per name, one
    sample per line, the labels escaped as the format asks."""
    lines, seen = [], set()
    for metric in metrics:
        name = metric['name']
        if name not in seen:
            seen.add(name)
            lines.append(f"# HELP {name} {metric['help']}")
            lines.append(f"# TYPE {name} {metric.get('type', 'gauge')}")
        labels = metric.get('labels') or {}
        label_text = ("{" + ",".join(
            f'{key}="{str(value).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
            for key, value in labels.items()) + "}") if labels else ""
        value = metric['value']
        lines.append(f"{name}{label_text} {int(value) if isinstance(value, bool) else value}")
    return "\n".join(lines) + "\n"


class TexoMetrics(models.AbstractModel):
    _name = 'texo.metrics'
    _description = "Texo Metrics"

    @api.model
    def _metric(self, name, help_text, value, labels=None, type_='gauge'):
        return {'name': name, 'help': help_text, 'type': type_, 'labels': labels or {}, 'value': value}

    @api.model
    def _collect(self):
        """The metrics of the hub: a list of samples; the modules add theirs with super()."""
        metrics = []
        for role, xmlid in HUB_ROLE_GROUPS:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            count = len(group.sudo().all_user_ids.filtered(lambda u: u.active and not u.share)) if group else 0
            metrics.append(self._metric('texo_users', "Users with a hub role (admin implies lead implies member).",
                                        count, {'role': role}))
        module = self.env['ir.module.module'].sudo().search([('name', '=', 'texo')], limit=1)
        metrics.append(self._metric('texo_info', "The hub: the version of the module texo.", 1,
                                    {'version': module.latest_version or ''}))
        return metrics

    @api.model
    def _render(self):
        return render(self._collect())
