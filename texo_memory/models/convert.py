# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The conversion of a document by a service next to the hub, optional.

A document of the memory keeps its converted text next to the original (ir_attachment.py), so the sessions
read it and the search finds its words. The conversion runs where the person wants it: on their machine
(scripts/ingest.py of the core, Docling or the light converters) or, when an administrator names a conversion
service in the system parameters, in the hub, which sends the file to the service and keeps the text it gives
back. The service is reached on the local network only, unless the administrator opts in, as for the
embeddings: an original of a customer leaves the hub for the converter and for nothing else.

Spoken to: docling-serve (POST /v1/convert/file, multipart, the Markdown of the document in the answer);
another converter with the same contract passes as api docling.
"""
import logging

import requests

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.texo.models.net import is_local_url

_logger = logging.getLogger(__name__)

PARAM_ENDPOINT = 'texo_memory.convert_endpoint'
PARAM_API = 'texo_memory.convert_api'
PARAM_TIMEOUT = 'texo_memory.convert_timeout'
PARAM_ALLOW_REMOTE = 'texo_memory.allow_remote_convert'
APIS = ('docling',)
DEFAULT_TIMEOUT = 300
# the answer of docling-serve: the Markdown of the document, under its key
DOCLING_PATH = ('document', 'md_content')


class MemoryConvert(models.AbstractModel):
    """The conversion service of the hub: its endpoint, its API, the call."""
    _name = 'memory.convert'
    _description = "Memory Document Conversion"

    @api.model
    def _param(self, key, type_='str', default=None):
        Params = self.env['ir.config_parameter'].sudo()
        getters = {'str': Params.get_str, 'int': Params.get_int, 'float': Params.get_float, 'bool': Params.get_bool}
        return getters[type_](key, default)

    @api.model
    def _endpoint(self):
        """The URL of the service, or None: not configured, or outside the local network without the opt-in."""
        url = (self._param(PARAM_ENDPOINT, 'str', '') or '').strip().rstrip('/')
        if not url:
            return None
        if not is_local_url(url) and not self._param(PARAM_ALLOW_REMOTE, 'bool', False):
            _logger.warning("The conversion endpoint %s is not on the local network and %s is not set: no document "
                            "is sent.", url, PARAM_ALLOW_REMOTE)
            return None
        return url

    @api.model
    def _state(self):
        """What a caller may expect: off (no endpoint), unavailable (named outside the local network without
        the opt-in), configured."""
        if not (self._param(PARAM_ENDPOINT, 'str', '') or '').strip():
            return 'off'
        return 'configured' if self._endpoint() else 'unavailable'

    @api.model
    def _convert(self, name, raw, mimetype):
        """The Markdown of a file from the service, or a UserError that says why not: no service, a service
        that does not answer in time, an answer without a text."""
        url = self._endpoint()
        if not url:
            raise UserError(self.env._(
                "No conversion service is named for this hub (%s): convert the document on your machine "
                "(ingest.py of the core) and write its text with document_write.", PARAM_ENDPOINT))
        api_name = (self._param(PARAM_API, 'str', 'docling') or 'docling').strip()
        if api_name not in APIS:
            raise UserError(self.env._("%(key)s is one of %(apis)s.", key=PARAM_API, apis=", ".join(APIS)))
        timeout = self._param(PARAM_TIMEOUT, 'int', DEFAULT_TIMEOUT)
        try:
            answer = requests.post(f"{url}/v1/convert/file", files={'files': (name, raw, mimetype or 'application/octet-stream')},
                                   data={'to_formats': 'md', 'image_export_mode': 'placeholder'}, timeout=timeout)
            answer.raise_for_status()
            data = answer.json()
        except (requests.RequestException, ValueError) as error:
            raise UserError(self.env._("The conversion service at %(url)s did not answer in %(timeout)s s or gave no "
                                       "text (%(error)s).", url=url, timeout=timeout, error=error)) from None
        text = data
        for key in DOCLING_PATH:
            text = text.get(key) if isinstance(text, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise UserError(self.env._("The conversion service at %s answered without a text.", url))
        return text
