# -*- coding: utf-8 -*-
"""
Vinculum - Digital Business Cards Module
Copyright (C) 2024 Faris Delija. All Rights Reserved.
Licensed under OPL-1 (Odoo Proprietary License v1.0)

Unauthorized copying, modification, or distribution prohibited.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestLookalikePerf(TransactionCase):
    """Opening a lead scores every company and open opportunity in the
    database. The query count must not grow with the size of that pool:
    at ~1,100 companies a per-partner query made each lead take 4 seconds.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # install_mode short-circuits the Vinc license guard on create/write.
        cls.env = cls.env(context=dict(cls.env.context, install_mode=True))
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Prospect',
            'type': 'opportunity',
            'city': 'Lookalikeville',
            'expected_revenue': 75_000,
        })

    def _add_companies(self, count, revenue):
        for i in range(count):
            partner = self.env['res.partner'].create({
                'name': 'Lookalike Co %s %s' % (revenue, i),
                'is_company': True,
                'city': 'Lookalikeville',
            })
            self.env['crm.lead'].create({
                'name': 'Deal %s' % partner.name,
                'partner_id': partner.id,
                'expected_revenue': revenue,
            })

    def _count_queries(self):
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        result = self.lead._find_lookalike()
        return self.env.cr.sql_log_count - before, result

    def test_query_count_flat_in_pool_size(self):
        self._add_companies(5, 5_000)
        small, _ = self._count_queries()
        self._add_companies(40, 5_000)
        large, _ = self._count_queries()
        self.assertLessEqual(large - small, 2, "lookalike queries grow with the company pool")

    def test_top_deal_drives_deal_size_band(self):
        self._add_companies(1, 5_000)     # micro: two bands from the 75k prospect
        self._add_companies(1, 120_000)   # mid: same band as the 75k prospect
        _, (partner_matches, _, _) = self._count_queries()
        top_partner, signals, payload = partner_matches[0]
        self.assertIn('120000', top_partner.name)
        self.assertIn('same deal-size band (mid)', signals)
        self.assertIn('$120,000', payload['outcome'])
