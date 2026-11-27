"""Expansion-risk labels, vintages, fitted forecasts, and cohort-accounting tests."""

import copy
import unittest

import numpy as np
import pandas as pd

from build_model import fit_logit, metrics, run_walk_forward, score
from expansion_trial import COMPLETE_CASE, FEATURES, PREDICTIONS, build_expansion_trial, onset_labels
from leading_trial import add_leading_features, build_leading_trial


class ExpansionTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dates = pd.date_range('1970-01', '2001-10', freq='MS')
        t = np.arange(len(dates))
        # Long and short recessions, plus expansion months with worsening signals.
        labels = pd.Series(((t % 64 >= 23) & (t % 64 < 30)).astype(float), index=dates)
        labels.loc[dates[-1]] = 1
        path = pd.concat([labels.shift(-i) for i in range(1, 13)], axis=1)
        cls.source = pd.DataFrame(
            dict(USREC=labels, PERMIT=1200 + 80 * np.cos(t / 8), ICSA=230000 + 15000 * np.sin(t / 7)),
            index=dates,
        )
        cls.panel = pd.DataFrame(
            dict(
                slope=1.1 + 1.6 * np.cos(t / 11),
                credit=np.cos(t / 8),
                labor=0.3 + np.sin(t / 5) * 0.18,
                recession=labels,
                target=path.max(axis=1).where(path.notna().all(axis=1)),
            ),
            index=dates,
        )
        records, _ = run_walk_forward(cls.panel)
        latest = dict(issueDate=str(dates[-1].date()), baselineProbability=0.2, probability=0.18)
        cls.leading = build_leading_trial(
            cls.panel, cls.source, pd.DataFrame(records), latest, fit_logit, score, metrics
        )
        cls.trial = cls.build()

    @classmethod
    def build(cls, panel=None, source=None, leading=None):
        return build_expansion_trial(
            cls.panel if panel is None else panel,
            cls.source if source is None else source,
            cls.leading if leading is None else leading,
            fit_logit,
            score,
            metrics,
        )

    def test_target_requires_expansion_first_transition_and_all_thirteen_released_months(self):
        dates = pd.date_range('2000-01', periods=37, freq='MS')
        labels = pd.Series(0.0, index=dates)
        labels.iloc[[3, 4, 5, 11, 24]] = 1
        source = pd.DataFrame({'USREC': labels})
        frozen = onset_labels(source, dates[-1])
        self.assertEqual(frozen.loc[dates[0], 'monthsToOnset'], 3)
        self.assertEqual(frozen.loc[dates[5], 'issueRecession'], 1)
        self.assertTrue(pd.isna(frozen.loc[dates[5], 'target']))
        self.assertEqual(frozen.loc[dates[6], 'onsetDate'], dates[11])
        self.assertEqual(frozen.loc[dates[12], 'monthsToOnset'], 12)
        self.assertTrue(pd.isna(frozen.loc[dates[24], 'target']))
        self.assertTrue(pd.isna(frozen.loc[dates[25], 'target']))
        self.assertNotIn(dates[-1], frozen.index)
        broken = source.drop(dates[1])
        gapped = onset_labels(broken, dates[-1])
        self.assertTrue(pd.isna(gapped.loc[dates[0], 'target']))
        self.assertTrue(pd.isna(gapped.loc[dates[1], 'issueRecession']))
        self.assertEqual(gapped.loc[dates[2], 'target'], 1)

    def test_all_fits_use_expansion_origin_and_mature_onset_only(self):
        expanded = add_leading_features(self.panel, self.source)
        flags = self.source.USREC
        final = self.trial['latest']
        last = dict(final, models={'candidate': self.trial['currentModel']})
        for fold in [*self.trial['folds'], last]:
            cutoff = pd.Timestamp(fold['refitDate']) - pd.DateOffset(months=13)
            train = expanded.loc[:cutoff].dropna(subset=COMPLETE_CASE)
            train = train.loc[flags.reindex(train.index).eq(0)]
            y = []
            onsets = set()
            for d in train.index:
                dates = pd.date_range(d, periods=13, freq='MS')
                track = flags.reindex(dates).tolist()
                self.assertTrue(all(v in (0, 1) for v in track))
                begins = [date for date, i, j in zip(dates[1:], track, track[1:]) if i == 0 and j == 1]
                y.append(int(bool(begins)))
                if begins:
                    onsets.add(begins[0])
            self.assertEqual(
                (fold['trainingN'], fold['trainingPositives'], fold['trainingOnsets']),
                (len(train), sum(y), len(onsets)),
            )
            self.assertLess(fold['lastTargetMonth'], fold['refitDate'])
            model = fold['models']['candidate']
            self.assertEqual(model['featureOrder'], FEATURES)
            check = fit_logit(train[FEATURES], pd.Series(y, index=train.index))
            np.testing.assert_allclose(check['coefficients'], model['coefficients'], atol=1e-10)

    def test_fixed_benchmark_crossed_controls_and_active_phase_independent_scoring(self):
        old = {r['date']: r for r in self.leading['history']}
        folds = {f['refitDate']: f['models']['candidate'] for f in self.trial['folds']}
        for r in [*self.trial['history'], dict(self.trial['latest'], date=self.trial['latest']['issueDate'])]:
            d = r['date']
            current = r.get('conditionalOnExpansion', False)
            original = self.leading['latest'] if current else old[d]
            self.assertEqual(r['benchmarkProbability'], original['permitsBlendProbability'])
            self.assertEqual(r['baselineProbability'], original['baselineProbability'])
            self.assertEqual(r['featureDate'], original['featureDate'])
            m = self.trial['currentModel'] if current else folds[r['refitDate']]
            raw = score(m, [[r[col] for col in FEATURES]])[0]
            rp = 2 * r['benchmarkProbability'] - r['baselineProbability']
            prior = r['trainingPositives'] / r['trainingN']
            self.assertAlmostEqual(r['rawExpansionProbability'], raw)
            self.assertAlmostEqual(r['expansionPriorProbability'], prior)
            self.assertAlmostEqual(r['probability'], (raw + prior) / 2)
            self.assertAlmostEqual(r['signalOnlyChangeProbability'], (raw + r['baselineProbability']) / 2)
            self.assertAlmostEqual(r['baseOnlyChangeProbability'], (rp + prior) / 2)
            if not current and r['issueRecession'] == 1:
                self.assertIsNone(r['target'])
                self.assertFalse(r['commonMature'])
                self.assertIsNotNone(r['probability'])
        # The last source row is excluded from the live clock irrespective of its phase.
        for phase in [0, 1, np.nan]:
            source = self.source.copy()
            source.iloc[-1, source.columns.get_loc('USREC')] = phase
            other = self.build(source=source)['latest']
            self.assertEqual(other['probability'], self.trial['latest']['probability'])
            self.assertTrue(other['available'] and other['conditionalOnExpansion'])
            self.assertNotIn('issueRecession', other)

    def test_scored_common_months_anchored_to_published_calendar(self):
        end = self.trial['metrics']['rolling120']['windowEnd']
        date = pd.Timestamp(end)
        # Exclude the last benchmark-origin from the permitted test features; window must stay fixed.
        trial = self.build(panel=self.panel.drop(date))
        self.assertEqual(
            trial['metrics']['rolling120']['windowStart'], str((date - pd.DateOffset(months=119)).date())
        )
        for key, m in trial['metrics'].items():
            paired = [
                r
                for r in trial['history']
                if r['commonMature'] and m['windowStart'] <= r['date'] <= m['windowEnd']
            ]
            self.assertEqual(len(paired), m['n'])
            self.assertTrue(all(r['issueRecession'] == 0 for r in paired))
            self.assertEqual(
                m['matureBenchmarkN'],
                m['expansionN'] + m['recessionN'] + m['unknownPhaseN'] + m['incompleteHorizonN'],
            )
            self.assertEqual(m['expansionN'], m['n'] + m['missingCandidateMonths'])
            self.assertEqual(m['distinctOnsets'], len({r['onsetDate'] for r in paired if r['target'] == 1}))
            for arm, field in PREDICTIONS.items():
                bs = np.mean([(r['target'] - r[field]) ** 2 for r in paired])
                self.assertAlmostEqual(bs, m['models'][arm]['brier'])
            self.assertEqual(
                trial['gate'][key + 'Passed'],
                m['models']['candidate']['brier'] < m['models']['benchmark']['brier'],
            )

    def test_source_gap_suppresses_outcome_and_future_labels_cannot_change_earlier_forecasts(self):
        source = self.source.copy()
        g = pd.Timestamp('1998-05-01')
        source.loc[g, 'USREC'] = np.nan
        trial = self.build(source=source)
        old = {r['date']: r for r in self.trial['history']}
        for r in trial['history']:
            date = pd.Timestamp(r['date'])
            if g <= date + pd.DateOffset(months=12) and date <= g:
                self.assertFalse(r['commonMature'])
                self.assertIsNone(r['target'])
            if date <= g:
                self.assertEqual(r['probability'], old[r['date']]['probability'])
        m = trial['metrics']['all']
        self.assertEqual(m['unknownPhaseN'], 1)
        self.assertGreater(m['incompleteHorizonN'], 0)

    def test_empty_and_unavailable_inputs_preserve_benchmark_and_do_not_create_evidence(self):
        trial = self.build(leading=dict(self.leading, history=[]))
        self.assertEqual(trial['metrics']['all']['n'], 0)
        self.assertFalse(trial['gate']['passed'])
        panel = self.panel.drop(self.panel.index[-1])
        missing = self.build(panel=panel)['latest']
        self.assertFalse(missing['available'])
        self.assertIsNone(missing['probability'])
        self.assertEqual(missing['benchmarkProbability'], self.leading['latest']['permitsBlendProbability'])
        unpublished = copy.deepcopy(self.leading)
        unpublished['latest']['permitsBlendProbability'] = None
        unpaired = self.build(leading=unpublished)['latest']
        self.assertFalse(unpaired['available'])
        self.assertIsNotNone(unpaired['rawExpansionProbability'])
        self.assertTrue(
            all(
                unpaired[k] is None
                for k in ['probability', 'signalOnlyChangeProbability', 'baseOnlyChangeProbability']
            )
        )
        bad = copy.deepcopy(self.leading)
        bad['history'][-1]['target'] = 0
        with self.assertRaisesRegex(ValueError, 'incomplete benchmark outcome'):
            self.build(leading=bad)


if __name__ == '__main__':
    unittest.main()
