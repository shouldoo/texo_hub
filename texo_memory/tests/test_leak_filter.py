# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.tests import tagged

from ..models.leak_filter import leak_reason
from .common import CLEAN_FINDING, MemoryCase


@tagged('post_install', '-at_install')
class TestLeakFilter(MemoryCase):

    def reason(self, text, source_ref=None):
        return leak_reason(self.env, text, source_ref)

    def test_clean_text_passes(self):
        self.assertIsNone(self.reason(CLEAN_FINDING))
        self.assertIsNone(self.reason("See https://github.com/OCA/purchase-workflow for the 20.0 branch of the module."))

    def test_customer_names_are_rejected_even_archived_or_opted_out(self):
        self.assertEqual(self.reason("The returns route of Rossi Meccanica needs a dedicated picking type."),
                         "it names a customer")
        self.customer.active = False
        self.assertEqual(self.reason("The returns route of rossi meccanica needs a dedicated picking type."),
                         "it names a customer")
        self.env['memory.optout.name'].create({'name': 'Bianchi Logistica'})
        self.assertEqual(self.reason("Bianchi Logistica asked for a second warehouse in the same company."),
                         "it names a customer")

    def test_each_class_of_leak_is_rejected(self):
        cases = {
            "Write to mario@example.com before you change the picking type of the returns.": "e-mail",
            "The customer portal is at https://erp.example.com/web and the route is set there.": "URL",
            "The yearly licence costs € 1200 and the discount is applied on the second line.": "amount",
            "The fix is on project.task/482 of the internal instance, see the chatter there.": "record",
            "Reported on ticket #4821: the picking type of the return has no default location.": "ticket",
            "[PERSONA:1] prefers the return to be validated by the warehouse manager every evening.": "pseudonym",
            "The source is the migration task MIG-2026-07 as written in the project notes of it.": "source",
        }
        for text, label in cases.items():
            with self.subTest(label=label):
                self.assertIsNotNone(self.reason(text, source_ref="MIG-2026-07"), label)

    def test_length_limits(self):
        self.assertIsNotNone(self.reason("too short"))
        self.assertIsNotNone(self.reason("x" * 2001))
        self.assertIsNone(leak_reason(self.env, "short", check_length=False))
