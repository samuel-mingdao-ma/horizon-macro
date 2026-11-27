"""Timing, baseline ceiling, paired coverage and false alarms on known synthetic histories."""

import unittest

import pandas as pd

from onset_diagnostics import build_onset_diagnostics
from weight_warning import build_weight_warnings


def labels(start='2000-01', end='2004-12', recessions=()):
    flags = pd.Series(0, index=pd.date_range(start, end, freq='MS'), dtype=float)
    for first, last in recessions:
        flags.loc[first:last] = 1
    return flags


def make_trial(flags, start, end):
    rows = []
    for date in pd.date_range(start, end, freq='MS'):
        future = flags.reindex(pd.date_range(date + pd.offsets.MonthBegin(1), periods=12, freq='MS'))
        target = int(future.max()) if future.notna().all() else None
        rows.append(
            dict(
                date=str(date.date()),
                featureDate=str((date - pd.DateOffset(months=2)).date()),
                commonMature=target is not None,
                target=target,
                recession=flags.get(date),
                existingBlendProbability=0.1,
                probability=0.1,
                originalDynamicProbability=0.1,
                fixedPermitsProbability=0.1,
                fixedRuleProbability=0.1,
                permitsBlendProbability=0.1,
                originalProbability=0.1,
                baselineProbability=0.1,
            )
        )
    metric = dict(
        windowStart=rows[0]['date'], windowEnd=rows[-1]['date'], n=sum(r['commonMature'] for r in rows)
    )
    metrics = dict(all=metric.copy(), rolling120=metric.copy())
    build_onset_diagnostics(rows, flags, metrics)
    return dict(history=rows, metrics=metrics)


def cutoff(trial, start, end):
    n = sum(start <= row['date'] <= end and row['commonMature'] for row in trial['history'])
    return dict(windowStart=start, windowEnd=end, n=n)


class WeightWarningTests(unittest.TestCase):
    def test_new_warning_includes_threshold_and_refuses_extra_quiet_false_alarms(self):
        flags = labels(recessions=[('2002-07', '2002-09')])
        trial = make_trial(flags, '2000-12', '2002-10')
        by_date = {r['date']: r for r in trial['history']}
        by_date['2002-06-01']['existingBlendProbability'] = 0.3
        by_date['2001-07-01']['probability'] = 0.3
        by_date['2001-07-01']['fixedRuleProbability'] = 0.3
        by_date['2001-07-01']['fixedPermitsProbability'] = 0.3
        by_date['2002-09-01']['probability'] = 0.9  # last recession month has a negative target
        report = build_weight_warnings(trial, flags)
        self.assertTrue(report['gate']['passed'])
        self.assertTrue(report['ruleGate']['passed'])
        window = report['windows']['all']
        self.assertEqual(window['completeEpisodes'], 1)
        self.assertEqual(window['comparison']['earlier'], 1)
        self.assertEqual(window['summary']['candidate']['meanLeadMonths'], 12)
        self.assertEqual(window['summary']['existingBlend']['meanLeadMonths'], 1)
        self.assertEqual(window['summary']['candidate']['meanCrossLeadMonths'], 12)
        self.assertEqual(window['summary']['candidate']['recessionIssuedAlerts'], 1)
        self.assertFalse(window['versusFixedPermits']['passes'])
        by_date['2001-05-01']['probability'] = 0.4
        window = build_weight_warnings(trial, flags)['windows']['all']
        self.assertEqual(window['summary']['candidate']['quietAlerts'], 1)
        self.assertAlmostEqual(window['summary']['candidate']['quietRate'], 1 / window['quietExpansionN'])
        self.assertFalse(window['comparison']['passes'])
        self.assertEqual(window['fixedRuleComparison']['earlier'], 1)

    def test_ongoing_alert_starts_outside_window_and_no_new_crossing_is_manufactured(self):
        flags = labels(recessions=[('2002-07', '2002-09')])
        trial = make_trial(flags, '2001-06', '2002-10')
        for row in trial['history']:
            row['existingBlendProbability'] = 0.3
            row['probability'] = 0.4
        trial['metrics']['rolling120'] = cutoff(trial, '2001-07-01', '2002-06-01')
        window = build_weight_warnings(trial, flags)['windows']['rolling120']
        alarm = window['episodes'][0]['methods']['existingBlend']
        self.assertEqual(alarm['leadMonths'], 12)
        self.assertEqual(alarm['firstAlertKind'], 'already-high')
        self.assertIsNone(alarm['firstCrossDate'])
        self.assertEqual(window['summary']['candidate']['meanCrossLeadMonths'], 0)
        self.assertEqual(window['comparison']['tied'], 1)
        self.assertTrue(window['comparison']['baselineAtCeiling'])
        self.assertFalse(window['comparison']['sufficient'])  # no quiet dates in this slice
        trial['history'] = trial['history'][1:]
        trial['metrics']['all']['n'] -= 1
        window = build_weight_warnings(trial, flags)['windows']['rolling120']
        alarm = window['episodes'][0]['methods']['candidate']
        self.assertEqual(alarm['firstAlertKind'], 'previous-unknown')
        self.assertTrue(alarm['firstCrossUncertain'])
        self.assertIsNone(window['summary']['candidate']['meanCrossLeadMonths'])

    def test_missing_and_partial_episodes_are_preserved_and_unobserved_leads_are_null(self):
        flags = labels('1988-01', '1994-12', [('1990-08', '1990-10'), ('1992-03', '1992-05')])
        trial = make_trial(flags, '1990-01', '1992-08')
        for row in trial['history']:
            if '1991-03-01' <= row['date'] < '1992-03-01':
                row['commonMature'] = False
        trial['metrics'] = {k: cutoff(trial, '1990-01-01', '1992-08-01') for k in trial['metrics']}
        window = build_weight_warnings(trial, flags)['windows']['all']
        self.assertEqual([r['coverage'] for r in window['episodes']], ['partial', 'unavailable'])
        self.assertEqual([r['availableMonths'] for r in window['episodes']], [7, 0])
        self.assertEqual(window['episodes'][0]['outsideWindowMonths'], 5)
        self.assertEqual(window['episodes'][1]['missingPairedMonths'], 12)
        self.assertIsNone(window['episodes'][0]['methods']['candidate']['leadMonths'])
        self.assertIsNone(window['summary']['candidate']['meanLeadMonths'])
        self.assertFalse(window['comparison']['sufficient'])
        # Onsets twelve months after the last paired-calendar boundary remain visible.
        trial['metrics']['rolling120'] = cutoff(trial, '1991-03-01', '1991-03-01')
        recent = build_weight_warnings(trial, flags)['windows']['rolling120']
        self.assertEqual([r['onsetDate'] for r in recent['episodes']], ['1992-03-01'])
        self.assertEqual(recent['episodes'][0]['coverage'], 'unavailable')

    def test_fully_observed_miss_contributes_zero_and_direction_is_paired(self):
        flags = labels('1998-01', '2005-12', [('2000-01', '2000-05'), ('2003-01', '2003-02')])
        trial = make_trial(flags, '1998-06', '2003-03')
        for r in trial['history']:
            if r['date'] == '1999-12-01':
                r['existingBlendProbability'] = 0.3
            if r['date'] == '2002-10-01':
                r['probability'] = 0.31
        w = build_weight_warnings(trial, flags)['windows']['all']
        self.assertEqual(w['completeEpisodes'], 2)
        self.assertEqual(w['summary']['candidate']['meanLeadMonths'], 1.5)
        self.assertEqual(w['summary']['existingBlend']['meanLeadMonths'], 0.5)
        self.assertEqual(w['summary']['candidate']['completeHits'], 1)
        self.assertEqual((w['comparison']['earlier'], w['comparison']['later']), (1, 1))
        self.assertIsNone(w['episodes'][0]['methods']['candidate']['leadMonths'])

    def test_label_gaps_do_not_create_onsets_and_comparisons_refuse_unpaired_rows(self):
        flags = labels(recessions=[('2002-07', '2002-09')])
        flags = flags.drop(pd.Timestamp('2002-06-01'))
        trial = make_trial(flags, '2000-12', '2002-10')
        self.assertEqual(build_weight_warnings(trial, flags)['windows']['all']['episodes'], [])
        trial['metrics']['all']['n'] += 1
        with self.assertRaisesRegex(ValueError, 'same paired'):
            build_weight_warnings(trial, flags)


if __name__ == '__main__':
    unittest.main()
