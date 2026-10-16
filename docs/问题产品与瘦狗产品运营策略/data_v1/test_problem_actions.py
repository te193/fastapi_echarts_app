import json
import unittest
from collections import Counter
from decimal import Decimal as D

from calculate_problem_actions import ROOT, OUT, bid_rule, price_action, rounded_bid, select_ads, latest, not_deleted


class RulesTest(unittest.TestCase):
    def test_price_does_not_cross_floor_after_rounding(self):
        self.assertEqual(price_action(D('10.01'),D('10'),D('12'))[0],('100102',D('10.00')))
        self.assertEqual(price_action(D('15'),D('10.005'),D('12.001'))[0],('100101',D('12.01')))
        self.assertIsNone(price_action(D('10'),D('10'),D('12'))[0])
        self.assertIsNone(price_action(D('20'),D('12'),D('10'))[0])

    def test_click_and_acos_boundaries(self):
        self.assertEqual(bid_rule(True,D(62),D(0),D(9),D(0))[0][0],'100201')
        self.assertEqual(bid_rule(True,D(63),D(0),D(9),D(0))[0][0],'100202')
        self.assertEqual(bid_rule(True,D(70),D(2),D(65),D(100))[0][0],'100205')
        self.assertEqual(bid_rule(True,D(70),D(2),D('65.01'),D(100))[0][0],'100206')
        self.assertIsNone(bid_rule(False,D(10),D(2),D(30),D(100))[0])
        self.assertEqual(bid_rule(False,D(10),D(2),D(50),D(100))[0][0],'100302')

    def test_ambiguous_rule_and_missing_limits_do_not_emit_amount(self):
        self.assertIsNone(bid_rule(True,D(40),D(1),D(60),D(100))[0])
        self.assertIsNone(bid_rule(False,D(40),D(0),D(60),D(0))[0])
        self.assertIsNone(rounded_bid(D('.2'),D('-.2'),False,None,None)[0])
        self.assertIsNone(rounded_bid(D('.02'),D('-.1'),False,D('.02'),D(1000))[0])
        self.assertEqual(rounded_bid(D('.04'),D('-.1'),True,D('.02'),D(1000))[0],D('.03'))

    def test_risk_first_limit_and_execution_dedup(self):
        def row(i,kind,spend,execution):
            return dict(country='德国',store='A',msku='1',action_id=i,action_type=kind,cost=spend,execution_key=execution)
        rows=[row('1','bid_increase',100,'up'),row('2','bid_decrease',10,'down'),row('3','keyword_negative_exact',20,'neg'),row('4','keyword_negative_exact',20,'neg')]
        selected,rejected=select_ads(rows)
        self.assertEqual({r['execution_key'] for r in selected},{'down','neg'})
        self.assertEqual(len(rejected),2)

    def test_deleted_latest_record_does_not_resurrect_old_enabled_entity(self):
        rows=[dict(id=1,profile_id='p',ad_id='a',create_time='2026-09-20',update_time=None,delete_flag="b'\\x00'"),
              dict(id=2,profile_id='p',ad_id='a',create_time='2026-09-21',update_time=None,delete_flag="b'\\x01'")]
        self.assertFalse(not_deleted(latest(rows,['profile_id','ad_id'])[('p','a')]))


class ActualOutputTest(unittest.TestCase):
    def test_real_output_invariants(self):
        actions=json.loads((OUT/'final_actions.json').read_text(encoding='utf-8'))
        blocked=json.loads((OUT/'blocked_candidates.json').read_text(encoding='utf-8'))
        products=json.loads((OUT/'products.json').read_text(encoding='utf-8'))
        source=json.loads((ROOT/'product_base.json').read_text(encoding='utf-8'))
        keys={(r['country'],r['store'],r['msku']) for r in source if r['source_roles']==['problem']}
        self.assertEqual(len(products),2079)
        self.assertEqual(len(keys),len(products))
        self.assertEqual(len({r['execution_key'] for r in actions}),len(actions))
        prices=Counter(); ads=Counter()
        for row in actions:
            key=row['country'],row['store'],row['msku']
            self.assertIn(key,keys)
            self.assertTrue(row['rule_code'].startswith('1'))
            self.assertEqual(row['status'],'MANUAL_REVIEW')
            self.assertNotIn('blocker',row)
            if row['action_type']=='price_decrease':
                prices[key]+=1
                self.assertLess(D(row['suggested_value']),D(row['current_value']))
                self.assertGreaterEqual(D(row['suggested_value']),D(row['p10']))
            else: ads[key]+=1
            if row['action_type']=='ad_enable':
                self.assertTrue(row['existing_structures'])
                self.assertTrue(all(not all(e[f]=='enabled' for f in ('product_ad_state','campaign_state','ad_group_state')) for e in row['existing_structures']))
            if row['action_type']=='keyword_negative_exact':
                self.assertEqual(row['orders'],0)
                self.assertGreaterEqual(D(row['clicks']),49)
        self.assertLessEqual(max(prices.values(),default=0),1)
        self.assertLessEqual(max(ads.values(),default=0),2)
        self.assertTrue(all(r['suggested_value'] is None and r['status']=='BLOCKED' for r in blocked))
        self.assertFalse({r['action_id'] for r in actions}&{r['action_id'] for r in blocked})


if __name__=='__main__': unittest.main()
