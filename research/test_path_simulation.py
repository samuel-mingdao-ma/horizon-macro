"""Check common calendar pricing, paired gates and the public draw-level audit."""

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from joint_stress import Issue
from path_calibration import prepare_calibration
from path_simulation import (
    MAY,
    FEB,
    ReplayIssue,
    _evaluate,
    _prepare,
    _collect,
    _gates,
    build_path_simulation,
    wilson,
)


class PathSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        snapshot = json.loads((cls.root / 'data/snapshot.json').read_bytes())
        cls.parents = [snapshot[k] for k in ('expansionTrial', 'momentumTrial', 'curveLegsTrial')]
        cls.calibration = prepare_calibration(root=cls.root, as_of=snapshot['meta']['generatedAt'])
        cls.calendar, cls.issues, cls.latest, cls.baseline = _prepare(*cls.parents)

    def test_unchanged_calendar_reproduces_published_cohorts_and_scores_exactly(self):
        zero = np.zeros((len(self.calendar), 3, 2))
        stats, timing = _collect(self.issues, zero, self.baseline)
        for period, w in stats.items():
            self.assertTrue((w['brierDelta'] == 0).all())
            self.assertTrue((w['logLossDelta'] == 0).all())
            self.assertTrue((w['levelQuiet'] == self.baseline[period]['quietAlerts']).all())
            self.assertTrue((w['brier'] == self.baseline[period]['brier']).all())
        self.assertTrue((timing['lead2001'] == self.baseline['ruleLead2001']).all())
        self.assertTrue((timing['levelLead2001'] == self.baseline['levelLead2001']).all())

    def test_vector_policy_replays_all_shared_months_under_each_issues_fit(self):
        n = 20
        rng = np.random.default_rng(733)
        shocks = rng.uniform(-20, 20, (len(self.calendar), n, 2))
        for issue in [self.issues[0], *(r for r in self.issues if r.date in (MAY, FEB)), self.latest]:
            result = _evaluate(issue, shocks, need_change=True)
            if result is None:
                self.assertIsNone(issue.model.base[-1])
                continue
            p, level, alert, change = result
            for i in range(n):
                _, exact = issue.model.full_point(shocks[issue.positions, i, :].tolist())
                self.assertAlmostEqual(p[i], exact['probability'], places=12)
                self.assertEqual(level[i], exact['levelAlert'])
                self.assertEqual(alert[i], exact['referenceAlert'])
                if change is not None:
                    self.assertAlmostEqual(change[i], exact['change3m'], places=11)

    def test_one_dated_move_is_shared_by_overlapping_forecasts(self):
        early = next(r for r in self.issues if r.date == MAY)
        later = next(r for r in self.issues if r.date == '2000-08-01')
        self.assertEqual(early.positions[-1], later.positions[0])
        shocks = np.zeros((len(self.calendar), 1, 2))
        shocks[early.positions[-1], 0, :] = (2, 5)
        p1, _, _, _ = _evaluate(early, shocks)
        p2, _, _, change = _evaluate(later, shocks, need_change=True)
        self.assertNotAlmostEqual(p1[0], early.model.base[-1], places=6)
        self.assertAlmostEqual(p2[0], later.model.base[-1], places=12)
        expected = later.model.base[-1] - later.model.risk(0, 3)
        self.assertAlmostEqual(change[0], expected, places=11)

    def test_joint_requires_all_gates_on_one_draw_and_comparators_can_disagree(self):
        timing = dict(lead2001=np.array([11, 11, 10, 11]), levelLead2001=np.array([10, 10, 10, 10]))
        timing.update({k: np.ones(4, dtype=bool) for k in ('mayAlert', 'febAlert', 'mayExtra', 'febExtra')})
        stats = {
            k: dict(
                brierDelta=np.array([-0.01, 0, -0.001, -0.01]),
                logLossDelta=np.array([0.01, 0, 0, 0]),
                ruleQuiet=np.array([2, 3, 2, 2]),
                levelQuiet=np.array([2, 3, 2, 1]),
            )
            for k in ('all', 'rolling120')
        }
        base = {k: {'quietAlerts': 2} for k in stats}
        f = _gates(stats, timing, base)
        np.testing.assert_array_equal(f['jointMatched'], [1, 1, 0, 0])
        np.testing.assert_array_equal(f['jointObserved'], [1, 0, 0, 1])
        np.testing.assert_array_equal(f['joint'], [1, 0, 0, 0])
        np.testing.assert_array_equal(f['jointStrict'], [0, 0, 0, 0])

    def test_csv_reconstructs_counts_intervals_and_cap_examples(self):
        n = 80
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'draws.csv'
            t = build_path_simulation(*self.parents, self.calibration, csv_path=path, draws=n, seed=100)
            with path.open() as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), n * len(t['scenarios']))
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        for scenario in t['scenarios']:
            rr = [r for r in rows if r['scenario'] == scenario['id']]
            self.assertEqual([int(r['draw']) for r in rr], list(range(1, n + 1)))
            for r in rr:
                scores = all(float(r[k]) <= 0 for k in ('allBrierDelta', 'recentBrierDelta'))
                logs = all(float(r[k]) <= 0 for k in ('allLogLossDelta', 'recentLogLossDelta'))
                matched = all(int(r[p + 'RuleQuiet']) <= int(r[p + 'LevelQuiet']) for p in ('all', 'recent'))
                observed = all(
                    int(r[p + 'RuleQuiet']) <= self.baseline[w]['quietAlerts']
                    for p, w in [('all', 'all'), ('recent', 'rolling120')]
                )
                lead = (
                    bool(int(r['mayAlert']))
                    and int(r['lead2001'] or 0) >= 11
                    and int(r['lead2001'] or 0) > int(r['levelLead2001'] or 0)
                )
                self.assertEqual(bool(int(r['joint'])), scores and matched and observed and lead)
                self.assertEqual(bool(int(r['jointStrict'])), bool(int(r['joint'])) and logs)
            count = sum(int(r['joint']) for r in rr)
            self.assertEqual(scenario['gates']['joint'], wilson(count, n))
            for ex in scenario['examples']:
                r = rr[ex['draw'] - 1]
                self.assertEqual(ex['passed'], bool(int(r['joint'])))
                self.assertEqual(ex['febExtra'], bool(int(r['febExtra'])))
                for k in ('mayPath', 'febPath'):
                    self.assertEqual(len(ex[k]), 4)
                    if scenario['capBp']:
                        self.assertTrue(
                            all(abs(o[f]) <= scenario['capBp'] for o in ex[k] for f in ('shortBp', 'longBp'))
                        )
        self.assertEqual(wilson(0, n)['interval'][0], 0)
        self.assertGreater(wilson(0, n)['interval'][1], 0)
        self.assertEqual(wilson(n, n)['interval'][1], 1)

    def test_missing_middle_or_yields_preserve_level_control(self):
        model = Issue([0.2, None, 0.21, 0.29], 0.1, -1, 20, -5, [-1, None, -0.9, -0.4])
        row = ReplayIssue(MAY, model, np.arange(4), 1, ('all',), 11)
        shocks = np.zeros((4, 2, 2))
        _, level, flag, change = _evaluate(row, shocks, need_change=True)
        np.testing.assert_array_equal(level, flag)
        self.assertIsNone(change)
        model.base[-1] = None
        self.assertIsNone(_evaluate(row, shocks))


if __name__ == '__main__':
    unittest.main()
