import unittest
from credit_diagnostics import build_credit_diagnostics, build_expansion_diagnostics
from test_weight_warning import labels, make_trial


class CreditDiagnosticsTests(unittest.TestCase):
    def test_credit_states_and_alert_changes_share_denominators(self):
        flags = labels(recessions=[('2002-07', '2002-09')])
        trial = make_trial(flags, '2000-12', '2002-10')
        trial['gate'] = {'allPassed': True, 'rolling120Passed': True}
        rows = {r['date']: r for r in trial['history']}
        for r in rows.values():
            r.update(benchmarkProbability=0.1, persistent=False, sudden=False)
        rows['2000-12-01'].update(persistent=True, sudden=True, benchmarkProbability=0.3)
        rows['2001-01-01'].update(persistent=True, sudden=None)
        rows['2001-07-01'].update(persistent=False, sudden=True, probability=0.3)
        rows['2002-06-01']['benchmarkProbability'] = 0.31
        w = build_credit_diagnostics(trial, flags)
        for window in ('all', 'rolling120'):
            s = w['windows'][window]
            buckets = {r['state']: r for r in w['buckets'][window]}
            self.assertEqual(sum(r['n'] for r in buckets.values()), s['n'])
            self.assertEqual(sum(r['quietN'] for r in buckets.values()), s['quietExpansionN'])
            self.assertEqual(buckets['both']['benchmarkQuietAlerts'], 1)
            self.assertEqual(buckets['unknown']['n'], 1)
            self.assertEqual(buckets['sudden']['observedRate'], 1)
            self.assertIsNone(buckets['persistent']['observedRate'])
            self.assertEqual(
                s['alertChanges'], dict(quietRemoved=1, quietAdded=0, preOnsetRemoved=1, preOnsetAdded=1)
            )
        self.assertTrue(w['jointGate']['passed'])
        rows['2001-02-01']['probability'] = 0.3
        w = build_credit_diagnostics(trial, flags)
        self.assertTrue(w['gate']['passed'])
        self.assertFalse(w['jointGate']['passed'])  # equal false alarms are insufficient


class ExpansionDiagnosticsTests(unittest.TestCase):
    def test_lagged_signal_month_can_still_be_in_recession(self):
        flags = labels(recessions=[('2001-04', '2001-06')])
        trial = make_trial(flags, '2001-07', '2001-10')
        # A missing earlier label affects coverage of the retrospective check, not the issued forecasts.
        flags = flags.drop('2001-08-01')
        trial['gate'] = dict(allPassed=False, rolling120Passed=False)
        for r in trial['history']:
            r.update(benchmarkProbability=.1, probability=.2)
        scope = build_expansion_diagnostics(trial, flags)['windows']['all']['expansionAtBothDates']
        self.assertEqual((scope['recessionSignalMonths'], scope['n'], scope['unknownSignalMonths']), (2, 1, 1))
        self.assertAlmostEqual(scope['benchmark'], .01)
        self.assertAlmostEqual(scope['candidate'], .04)


if __name__ == '__main__':
    unittest.main()
