"""Test both Treasury legs, the pre-specified warnings, and the separately frozen shadow rule."""

import copy
import unittest

import pandas as pd

from curve_legs import ALERTS, PRE_REPLAY, RULES, SPEC, _gates, build_curve_legs_trial, leg_decisions, leg_evidence
from forecast_ledger import month_offset
from pace_trial import CASE_DATE, CASE_ONSET, build_pace_trial
from test_pace_trial import fixture


def path(short, long):
    return [dict(date=month_offset('2000-03-01', i-3), shortYield=s, longYield=l)
            for i, (s, l) in enumerate(zip(short, long))]


def replay():
    expansion, recession = fixture()
    index = pd.to_datetime([r['featureDate'] for r in expansion['history']])
    bills = pd.Series([4 + j/100 for j in range(len(index))], index=index)
    bonds = bills + [row['slope'] for row in expansion['history']]
    raw = dict(TB3MS=bills, GS10=bonds, USREC=recession)
    momentum = build_pace_trial(expansion, recession)
    return expansion, momentum, raw


class TreasuryLegTests(unittest.TestCase):
    def test_signed_leg_identity_driver_ties_pure_and_offsets(self):
        for short, long, driver, pattern, flattening in [
            (5.49, 5.98, 'short-led', 'both-flatten', .51),
            (5.10, 5.72, 'long-led', 'both-flatten', .38),
            (5.10, 5.90, 'equal', 'both-flatten', .20),
            (5.10, 6, 'short-led', 'short-only', .10),
            (5, 5.90, 'long-led', 'long-only', .10),
            (5.70, 6.50, 'short-led', 'long-rise-offset', .20),
            (4.50, 5.30, 'long-led', 'short-fall-offset', .20),
            (5.10, 6.10, 'no-flattening', 'no-flattening', 0),
            (5, 6.10, 'no-flattening', 'no-flattening', -.10),
        ]:
            with self.subTest(short=short, long=long):
                r = leg_evidence(path([5,5.10,5.20,short], [6,None,None,long]))
                self.assertEqual((r['driver'],r['pattern'],r['flattening']), (driver,pattern,flattening))
                self.assertAlmostEqual(r['shortChange']-r['longChange'], flattening, places=12)
                self.assertAlmostEqual(r['startSlope']-r['endSlope'], flattening, places=12)
        rounded = leg_evidence(path([5,5,5,5.1+1e-13], [6,None,None,5.9]))
        self.assertEqual(rounded['driver'],'equal')

    def test_four_distinct_filters_with_exact_ties(self):
        self.assertEqual(SPEC['preReplayRules'],list(PRE_REPLAY))
        self.assertEqual(SPEC['postHocRules'],['mixedTwoToOne'])
        for short, long_end, eligible in [
            ([3,3.1,3.2,3.4], 4.8, (True,False,True,True)),   # exactly twice the fall
            ([3,3.1,3.2,3.4], 4.79, (True,False,True,False)),
            ([3,3.1,3.2,3.4], 5, (True,True,True,True)),     # flat long end qualifies for both
            ([3,3.1,3.2,3.4], 5.01, (True,True,True,False)), # even a small long rise excludes shadow
            ([3,3.1,3.1,3.4], 4.8, (True,False,False,True)),
            ([3,3.1,3.2,3.4], 4.6, (False,False,False,False)),
        ]:
            r = leg_evidence(path(short,[5,5,5,long_end]))
            self.assertEqual(tuple(r[k] for k in RULES),eligible)
            self.assertEqual(tuple(leg_decisions(False,True,r).values()),eligible)
            self.assertTrue(all(leg_decisions(True,True,r).values()))
            self.assertFalse(any(leg_decisions(False,False,r).values()))
            self.assertTrue(all(v is None for v in leg_decisions(None,None,r).values()))

    def test_missing_inputs_use_only_required_observations_and_exact_calendar_months(self):
        r = leg_evidence(path([4, None, 4.2, 4.3], [5, None, None, 5.1]))
        self.assertTrue(r['bear'])
        self.assertIsNone(r['sustained'])
        self.assertIsNone(r['shortRiseCount'])
        self.assertFalse(leg_decisions(False,True,r)['sustainedAlert'])
        missing = leg_evidence(path([4,4.1,4.2,4.3], [None, 5.1, 5.1, 5.1]))
        self.assertEqual((missing['driver'], missing['shortChange'], missing['longChange']), ('unavailable',.3,None))
        self.assertTrue(all(v is None for v in [missing[k] for k in RULES]))
        self.assertTrue(all(leg_decisions(True,True,missing).values()))
        with self.assertRaises(ValueError):
            leg_decisions(True,False,missing)
        points = path([1]*4, [2]*4)
        points[1]['date'] = points[0]['date']
        with self.assertRaisesRegex(ValueError, 'consecutive'):
            leg_evidence(points)
        for item in points:
            item['date'] = item['date'][:-2]+'15'
        with self.assertRaisesRegex(ValueError, 'consecutive'):
            leg_evidence(points)

    def test_paired_mature_cohorts_monthly_clock_and_immutable_probabilities(self):
        expansion, momentum, raw = replay()
        t = build_curve_legs_trial(expansion,momentum,raw)
        self.assertEqual(len(t['history']),len(momentum['history']))
        for row, p in zip(t['history'],momentum['history']):
            self.assertEqual(next(iter(row)), 'date')
            self.assertEqual(row['probability'],p['probability'])
            self.assertEqual(row['commonMature'],p['commonMature'])
            self.assertEqual(row['featureDate'],month_offset(row['date'],-2))
            self.assertEqual(row['lagFeatureDate'],month_offset(row['date'],-5))
            for k in RULES:
                self.assertTrue(row['levelAlert'] <= row[ALERTS[k]] <= row['quarterAlert'])
        self.assertEqual(t['latest']['probability'],momentum['latest']['probability'])
        self.assertNotEqual(t['latest']['probability'],t['history'][-1]['probability'])
        path_dates = [pt['date'] for pt in t['latest']['yieldPath']]
        self.assertEqual(path_dates,[month_offset(t['latest']['issueDate'],i) for i in range(-5,-1)])
        for key,w in t['windows'].items():
            parent=momentum['windows'][key]
            self.assertEqual(w['probabilityScores'], parent['probabilityScores'])
            for k in ('n','quietExpansionN','preOnsetN','completeEpisodes'):
                self.assertEqual(w[k], parent[k])
            for k in ('level','quarter'):
                self.assertEqual(w['summary'][k],parent['summary'][k])
            for k in ('quarter',*RULES):
                self.assertEqual(len(w['changes'][k]['quietDates']), w['summary'][k]['quietAlerts']-w['summary']['level']['quietAlerts'])
        for case in t['caseEffects'].values():
            if case:
                self.assertAlmostEqual(case['shortEffect']+case['longEffect'],case['curveEffect'],places=12)
        missing = raw.copy()
        missing['TB3MS'] = raw['TB3MS'].drop(pd.Timestamp(t['latest']['lagFeatureDate']))
        sparse = build_curve_legs_trial(expansion,momentum,missing)
        self.assertEqual(sparse['latest']['driver'],'unavailable')
        self.assertEqual(sparse['windows']['all']['n'],t['windows']['all']['n'])
        for k in RULES:
            self.assertEqual(sparse['latest'][ALERTS[k]],t['latest']['levelAlert'])

    def test_bad_source_dates_spreads_or_parent_issues_are_rejected(self):
        expansion, momentum, raw = replay()
        duplicate=dict(raw, GS10=pd.concat([raw['GS10'],raw['GS10'].tail(1)]))
        with self.assertRaisesRegex(ValueError,'calendar-month'):
            build_curve_legs_trial(expansion,momentum,duplicate)
        wrong=dict(raw, TB3MS=raw['TB3MS']+.01)
        with self.assertRaisesRegex(ValueError,'published slope'):
            build_curve_legs_trial(expansion,momentum,wrong)
        broken = copy.deepcopy(momentum)
        broken['history'][0]['featureDate'] = broken['history'][0]['date']
        with self.assertRaisesRegex(ValueError,'same-issue'):
            build_curve_legs_trial(expansion,broken,raw)
        broken = copy.deepcopy(momentum)
        broken['history'].pop(3)
        with self.assertRaisesRegex(ValueError,'same ordered'):
            build_curve_legs_trial(expansion,broken,raw)

    def test_gate_checks_actual_may_and_each_sample(self):
        comp = {k+'Comparison':dict(maintainedHits=True,noMoreFalseAlarms=True,sufficient=True) for k in RULES}
        ep = dict(onsetDate=CASE_ONSET,coverage='full',methods={k:dict(leadMonths=11) for k in ('level',*RULES)})
        ep['methods']['level']['leadMonths']=10
        w=dict(all=dict(episodes=[ep],**copy.deepcopy(comp)),rolling120=copy.deepcopy(comp))
        may=dict(date=CASE_DATE,commonMature=True,target=1,onsetDate=CASE_ONSET,levelAlert=False,quarterAlert=True,
                 **{ALERTS[k]: True for k in RULES})
        self.assertTrue(all(g['passed'] for g in _gates(w,may).values()))
        w['rolling120']['shortLeadComparison']['noMoreFalseAlarms']=False
        w['all']['bearComparison']['noMoreFalseAlarms']=False
        ep['methods']['sustained']['leadMonths']=10
        may['mixedTwoToOneAlert']=False
        self.assertFalse(any(g['passed'] for g in _gates(w,may).values()))


if __name__ == '__main__':
    unittest.main()
