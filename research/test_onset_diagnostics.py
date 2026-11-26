"""Checks for the evaluation-only onset and calibration audit."""

from pathlib import Path
import unittest

import pandas as pd

from onset_diagnostics import build_onset_diagnostics


def iso(month):
    return pd.Timestamp(month).date().isoformat()


def issue(month, target, inc=0.4, candidate=0.3, common=True):
    return dict(
        date=iso(month),
        featureDate=iso(pd.Timestamp(month) - pd.DateOffset(months=2)),
        target=target,
        existingBlendProbability=inc,
        probability=candidate,
        commonMature=common,
        originalProbability=0.6,
        permitsBlendProbability=0.5,
        baselineProbability=0.2,
        credit=0.0,
        labor=0.1,
        slope=1.0,
        permitGrowth6=2.0,
        claimsGrowth12=3.0,
    )


def report(rows, labels):
    dates = [row['date'] for row in rows]
    win = dict(windowStart=min(dates), windowEnd=max(dates), n=sum(row['commonMature'] for row in rows))
    return build_onset_diagnostics(rows, labels, dict(all=win, rolling120=win))


def series(start, end):
    return pd.Series(0.0, index=pd.date_range(start, end, freq='MS'))


class OnsetTests(unittest.TestCase):
    def test_actual_convention_leads_and_final_recession_month(self):
        labels = pd.read_csv(Path(__file__).parent / 'raw' / 'USREC.csv', index_col=0, parse_dates=True).USREC
        rows = [
            issue('2019-03', 1),
            issue('2019-09', 1),
            issue('2020-02', 1),
            issue('2020-03', 1),
            issue('2020-04', 0),
        ]
        audit = report(rows, labels)
        self.assertEqual([row['monthsToOnset'] for row in rows], [12, 6, 1, None, None])
        self.assertEqual([row['issuePhase'] for row in rows], ['pre-onset'] * 3 + ['recession-issued'] * 2)
        self.assertEqual(audit['episodes'][0]['onsetDate'], '2020-03-01')
        for name in ['pre1to3', 'pre4to6', 'pre7to12']:
            self.assertEqual(audit['windows']['all']['groups'][name]['n'], 1)
        self.assertEqual(audit['windows']['all']['groups']['recessionIssued']['positiveWindows'], 1)
        self.assertEqual(audit['windows']['all']['groups']['preOnset']['incumbentBelowRawN'], 3)

    def test_calibration_includes_quiet_months_and_uses_own_bin_edges(self):
        labels = series('2018-01', '2022-12')
        labels.loc['2020-03-01'] = 1
        rows = [
            issue('2018-02', 0, 0, 1),
            issue('2018-03', 0, 0.1, 0.6),
            issue('2019-03', 1, 0.4, 0.1),
            issue('2020-03', 0, 1, 0),
        ]
        win = report(rows, labels)['windows']['all']
        self.assertEqual(win['groups']['allExpansion']['n'], 3)
        self.assertEqual(win['groups']['allExpansion']['permitsBrier'], 0.25)
        self.assertEqual(win['groups']['allExpansion']['permitsMean'], 0.5)
        self.assertAlmostEqual(win['groups']['allExpansion']['observedRate'], 1 / 3)
        inc_bins = win['calibration']['incumbent']
        self.assertEqual([cell['n'] for cell in inc_bins], [1, 1, 0, 1, 0])
        self.assertIsNone(inc_bins[2]['observedRate'])
        self.assertEqual([cell['n'] for cell in win['calibration']['candidate']], [0, 1, 0, 0, 2])

    def test_missing_and_immature_labels_are_unknown_including_missing_label_after_onset(self):
        labels = series('2015-01', '2022-07')
        labels.loc['2017-03-01'] = 1
        labels.loc['2017-05-01'] = float('nan')
        rows = [issue('2017-02', 1), issue('2017-05', 0), issue('2022-01', None, common=False)]
        win = report(rows, labels)['windows']['all']
        self.assertEqual(win['unclassifiedN'], 2)
        self.assertTrue(all(row['issuePhase'] is None for row in rows))
        self.assertEqual(win['groups']['allExpansion']['n'], 0)

    def test_phase_is_annotation_and_downstream_data_cannot_change_an_earlier_window(self):
        labels = series('2010-01', '2014-01')
        rows = [issue('2011-01', 0)]
        original = rows[0].copy()
        one = report(rows, labels)
        labels.loc['2012-02-01'] = 1
        two = report(rows, labels)
        self.assertEqual(one, two)
        self.assertEqual({name: rows[0][name] for name in original}, original)
        self.assertEqual(set(rows[0]) - set(original), {'issuePhase', 'onsetDate', 'monthsToOnset'})

    def test_mismatched_outcome_is_rejected_and_unmatched_forecast_excluded(self):
        labels = series('2010-01', '2014-01')
        with self.assertRaisesRegex(ValueError, 'disagree'):
            report([issue('2010-06', 1)], labels)
        data = report([issue('2010-01', 0, common=False), issue('2010-02', 0)], labels)
        self.assertEqual(data['windows']['all']['n'], 1)


if __name__ == '__main__':
    unittest.main()
