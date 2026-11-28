"""Confirmations should change only eligible warnings, on dates observable at issue."""

import copy
from math import fsum
import unittest

from confirmation_trial import (
    ALERTS, CASE_DATES, RULES, build_confirmation_trial, case_attribution,
    confirmation_decisions, evaluation_gates, signal_evidence,
)
from forecast_ledger import month_offset
from pace_trial import CASE_DATE, CASE_ONSET, build_pace_trial
from test_pace_trial import fixture, model


class ConfirmationTests(unittest.TestCase):
    def test_zero_cutoffs_and_three_month_directions_independently(self):
        evidence = signal_evidence(
            dict(permitGrowth6=-1.0, claimsGrowth12=2.0, credit=-.03),
            dict(permitGrowth6=-2.0, claimsGrowth12=3.0, credit=-.04),
        )
        self.assertEqual((evidence['pressureVotes'], evidence['directionVotes']), (3, 1))
        self.assertTrue(evidence['creditTightening'])
        # Equality at the published twelve-decimal precision cannot cast a vote.
        boundary = signal_evidence(dict(permitGrowth6=-2e-13, claimsGrowth12=2e-13, credit=.1000000000001),
                                   dict(permitGrowth6=0, claimsGrowth12=0, credit=.1))
        self.assertEqual((boundary['pressureVotes'], boundary['directionVotes']), (0, 0))
        partial = signal_evidence(dict(permitGrowth6=-1, claimsGrowth12=2, credit=1), dict(credit=.1))
        self.assertEqual(partial['pressureVotes'], 3)
        self.assertIsNone(partial['directionVotes'])
        missing = signal_evidence(dict(permitGrowth6=-1, claimsGrowth12=2), None)
        self.assertIsNone(missing['pressureVotes'])
        self.assertIsNone(missing['creditTightening'])

    def test_alerts_require_parent_pace_and_complete_rule_specific_vote_counts(self):
        cases = [
            ((True, True, None, None), (True, True, True)),
            ((False, False, 3, 3), (False, False, False)),
            ((False, True, 3, None), (True, False, True)),
            ((False, True, 2, 3), (False, True, True)),
            ((False, True, None, None), (False, False, False)),
            ((None, None, 3, 3), (None, None, None)),
        ]
        for arguments, expected in cases:
            flags = confirmation_decisions(*arguments)
            self.assertEqual(tuple(flags[ALERTS[k]] for k in RULES), expected)
        for invalid in [(True, False, 3, 3), (None, True, 3, 3), (False, True, 4, 3), (False, True, 1.5, 2)]:
            with self.assertRaises(ValueError):
                confirmation_decisions(*invalid)

    def test_paired_replay_reuses_scores_and_each_dated_latest_or_historical_ledger_input(self):
        expansion, raw = fixture()
        momentum = build_pace_trial(expansion, raw)
        trial = build_confirmation_trial(expansion, momentum, raw)
        origins = {r['date']: r for r in expansion['history']}
        for row in trial['history'] + [trial['latest']]:
            d = row.get('issueDate', row.get('date'))
            source = expansion['latest'] if 'issueDate' in row else origins[d]
            self.assertEqual(row['probability'], source['probability'])
            self.assertEqual(row['featureDate'], month_offset(d, -2))
            self.assertEqual(row['lagFeatureDate'], month_offset(d, -5))
            old = origins.get(month_offset(d, -3))
            for field, result in signal_evidence(source, old).items():
                self.assertEqual(row[field], result)
            for key in RULES:
                self.assertTrue(row['levelAlert'] <= row[ALERTS[key]] <= row['quarterAlert'])
        self.assertNotEqual(trial['latest']['probability'], trial['history'][-1]['probability'])
        for period, w in trial['windows'].items():
            self.assertEqual(w['probabilityScores'], expansion['metrics'][period]['models']['candidate'])
            self.assertEqual(w['summary']['level'], momentum['windows'][period]['summary']['level'])
            self.assertEqual(w['summary']['quarter'], momentum['windows'][period]['summary']['quarter'])
            base = w['summary']['level']
            for key in RULES:
                dates = w['changes'][key]
                self.assertEqual(len(dates['quietDates']), w['summary'][key]['quietAlerts'] - base['quietAlerts'])
                self.assertEqual(len(dates['preOnsetDates']), w['summary'][key]['preOnsetAlerts'] - base['preOnsetAlerts'])
        self.assertEqual(set(trial['caseAttribution']), set(CASE_DATES))
        self.assertIsNone(trial['caseAttribution']['2019-02-01'])

    def test_missing_exact_lag_uses_baseline_and_misdated_inputs_are_rejected(self):
        expansion, raw = fixture()
        current = expansion['latest']['issueDate']
        removed = month_offset(current, -3)
        expansion['history'] = [r for r in expansion['history'] if r['date'] != removed]
        for metric in expansion['metrics'].values():
            metric['n'] -= 1
        pace = build_pace_trial(expansion, raw)
        trial = build_confirmation_trial(expansion, pace, raw)
        row = trial['latest']
        self.assertIsNone(row['lagCredit'])
        self.assertIsNone(row['pressureVotes'])
        self.assertTrue(all(row[ALERTS[k]] == row['levelAlert'] for k in RULES))
        broken = copy.deepcopy(pace)
        broken['latest']['featureDate'] = current
        with self.assertRaisesRegex(ValueError, 'aligned'):
            build_confirmation_trial(expansion, broken, raw)
        broken = copy.deepcopy(pace)
        broken['history'].pop()
        with self.assertRaisesRegex(ValueError, 'same ordered'):
            build_confirmation_trial(expansion, broken, raw)
        broken = copy.deepcopy(pace)
        broken['history'][0]['target'] = -1
        with self.assertRaisesRegex(ValueError, 'outcome'):
            build_confirmation_trial(expansion, broken, raw)

    def test_success_gate_needs_may_advance_and_no_added_quiet_in_each_period(self):
        comparisons = {key+'Comparison': dict(maintainedHits=True,noMoreFalseAlarms=True,sufficient=True) for key in RULES}
        event = dict(onsetDate=CASE_ONSET,coverage='full',methods={key:dict(leadMonths=11) for key in ('level',*RULES)})
        event['methods']['level']['leadMonths'] = 10
        w = dict(all=dict(episodes=[event],**copy.deepcopy(comparisons)), rolling120=copy.deepcopy(comparisons))
        may = dict(commonMature=True,target=1,onsetDate=CASE_ONSET,levelAlert=False,quarterAlert=True,
                   pressureAlert=True,directionAlert=True,breadthAlert=True)
        self.assertTrue(all(g['passed'] for g in evaluation_gates(w, may).values()))
        w['rolling120']['pressureComparison']['noMoreFalseAlarms'] = False
        event['methods']['direction']['leadMonths'] = 10
        may['breadthAlert'] = False
        result = evaluation_gates(w, may)
        self.assertTrue(result['pressure']['mayRetained'])
        self.assertFalse(result['direction']['mayRetained'])
        self.assertFalse(result['breadth']['mayRetained'])
        self.assertTrue(all(not g['passed'] for g in result.values()))

    def test_straight_path_probability_effects_telescope_at_zero_and_near_cancellation(self):
        estimate = model(CASE_DATE, 0)
        estimate['coefficients'] = [2., -2., 0., 0.]
        a = {k: 0. for k in estimate['featureOrder']}
        b = dict(a, slope=1., credit=1., refitDate=CASE_DATE)
        pace = dict(paceAvailable=True, lag3Probability=.30, probability=.30, change3m=0.)
        contrasts = case_attribution(a, b, pace, estimate)
        self.assertAlmostEqual(contrasts['effects']['slope'], .25)
        self.assertAlmostEqual(contrasts['effects']['credit'], -.25)
        self.assertEqual(fsum(contrasts['effects'].values()), 0.)
        b['slope'] += 1e-13
        near = case_attribution(a, b, pace, estimate)
        self.assertAlmostEqual(fsum(near['effects'].values()), 0., places=12)
        self.assertAlmostEqual(near['effects']['slope'], .25, places=12)
        self.assertIsNone(case_attribution(None, b, pace, estimate))
        self.assertIsNone(case_attribution(a, b, dict(pace, paceAvailable=False), estimate))
        self.assertIsNone(case_attribution(a, dict(b,labor=None), pace, estimate))
        with self.assertRaisesRegex(ValueError, 'reproduce'):
            case_attribution(a,b,dict(pace, probability=.65),estimate)


if __name__ == '__main__':
    unittest.main()
