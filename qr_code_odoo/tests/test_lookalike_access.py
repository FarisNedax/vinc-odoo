# -*- coding: utf-8 -*-
from odoo.tests import new_test_user, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestLookalikeAccess(TransactionCase):
    """A salesperson limited to own documents opens her lead: a matching
    colleague's lead must not be listed (it raised AccessError on open)."""

    def test_own_documents_user_opens_lead(self):
        env = self.env(context=dict(self.env.context, install_mode=True))
        rep = new_test_user(env, 'lookalike_rep', groups='sales_team.group_sale_salesman')
        other = new_test_user(env, 'lookalike_other', groups='sales_team.group_sale_salesman')
        vals = {'type': 'opportunity', 'city': 'Lookalikeville', 'expected_revenue': 75_000, 'probability': 30}
        mine = env['crm.lead'].create(dict(vals, name='Mine', user_id=rep.id))
        theirs = env['crm.lead'].create(dict(vals, name='Theirs', user_id=other.id))
        self.assertIn(theirs, mine.lookalike_lead_ids, 'as superuser the colleague lead matches')
        mine_as_rep = mine.with_user(rep)
        mine_as_rep.invalidate_recordset()
        data = mine_as_rep.web_read({'lookalike_lead_ids': {'fields': {'display_name': {}}}})
        self.assertNotIn(theirs.id, [r['id'] for r in data[0]['lookalike_lead_ids']])
