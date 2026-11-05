# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import fields, models


class MemorySourceSegment(models.Model):
    """A passage of a video card, written by whoever watched it: from when to when, who speaks,
    what is said in their own words, at most a short quote. No transcript of someone else's
    video is kept."""
    _name = 'memory.source.segment'
    _description = "External Source Video Segment"
    _order = 'item_id, sequence, id'

    item_id = fields.Many2one('memory.source.item', string="Card", required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    start = fields.Char(help="Where it starts, as minutes:seconds (e.g. 1:20).")
    end = fields.Char(help="Where it ends, as minutes:seconds.")
    speaker = fields.Char()
    summary = fields.Text(required=True, help="What is said, in your words.")
    quote = fields.Char(help="A short quote, between quotation marks.")
    company_id = fields.Many2one(related='item_id.company_id', store=True, index=True)
