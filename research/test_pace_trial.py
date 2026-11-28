"""Risk momentum uses dated, same-fit inputs and never changes the probability cohort."""

import copy
import math
import unittest

import pandas as pd

from build_model import metrics
from expansion_trial import COMPLETE_CASE, FEATURES
from forecast_ledger import month_offset
from pace_trial import ALERTS, CASE_DATE, CASE_ONSET, build_pace_trial, case_comparison, decisions


def model(refit, intercept):
    return dict(
        refitDate=refit, trainingPrevalence=0.1, featureOrder=FEATURES,
        means=[0.0] * 4, scales=[1.0] * 4, coefficients=[1.0, 0, 0, 0], intercept=intercept,
    )


def risk(slope, intercept):
    return (1 / (1 + math.exp(-slope - intercept)) + 0.1) / 2


def fixture():
    dates = pd.date_range('1999-01-01', '2002-10-01', freq='MS')
    flags = pd.Series(0, index=pd.date_range('1998-01-01', '2003-12-01', freq='MS'))
    flags.loc['2001-04-01':'2001-06-01'] = 1
    folds = {year: model(f'{year}-01-01', 0.35 * (year - 1999)) for year in range(1999, 2003)}
    rows = []
    for i, stamp in enumerate(dates):
        date = stamp.date().isoformat()
        fit = folds[stamp.year]
        x = -1.25 + 0.95 * math.sin(i / 3)
        positive = '2000-04-01' <= date < CASE_ONSET
        inside = bool(flags[stamp])
        rows.append(dict(
            date=date, featureDate=month_offset(date, -2), **{c: x for c in COMPLETE_CASE},
            refitDate=fit['refitDate'], expansionPriorProbability=0.1, probability=risk(x, fit['intercept']),
            commonMature=not inside, target=None if inside else int(positive),
            issuePhase='recession-issued' if inside else 'pre-onset' if positive else 'expansion-no-recession',
            onsetDate=CASE_ONSET if positive else None,
        ))
    recent = '2000-01-01'
    def window(start):
        paired = [r for r in rows if r['commonMature'] and r['date'] >= start]
        scores = metrics([r['target'] for r in paired], [r['probability'] for r in paired])
        return dict(windowStart=start, windowEnd=rows[-1]['date'], n=len(paired), models={'candidate': scores})
    date = rows[-1]['date']
    live = model(date, 0.2)
    latest = dict(rows[-1], issueDate=date, available=True, reason=None, refitDate=date,
                  probability=risk(rows[-1]['slope'], live['intercept']),
                  forecastStart=month_offset(date, 1), forecastEnd=month_offset(date, 12))
    return dict(
        history=rows, folds=[dict(refitDate=f['refitDate'], models={'candidate': f}) for f in folds.values()],
        currentModel=live, latest=latest, metrics={'all': window(rows[0]['date']), 'rolling120': window(recent)},
    ), flags


class MomentumTests(unittest.TestCase):
    def test_integer_thresholds_latest_rise_and_slow_vs_fast_control(self):
        for path, expected in [
            ([.1, .17, .19, .20], [False, True, False]),     # exactly at floor and quarter boundary
            ([.14, .17, .19, .26], [False, True, True]),     # exactly at one-month boundary
            ([.02, .08, .1, .19999], [False, False, False]),
            ([.15, .18, .27, .27], [False, False, False]),
            ([.28, .21, .22, .25], [False, False, False]),
            ([.255, .26, .27, .275], [False, False, False]),
            ([None, None, None, .30], [True, True, True]),
            ([.13, None, .20, .26], [False, False, False]),
            ([.1, .11, .22, None], [None, None, None]),
        ]:
            decision = decisions(path)
            self.assertEqual([decision[field] for field in ALERTS.values()], expected, path)
            self.assertEqual(decision['paceAvailable'], None not in path)
        for invalid in [[.9] * 3, [.2, .3, None, 1.001], [float('nan')] * 4]:
            with self.assertRaises(ValueError):
                decisions(invalid)

    def test_each_historical_and_monthly_path_reprices_inputs_under_current_fit(self):
        expansion, labels = fixture()
        result = build_pace_trial(expansion, labels)
        inputs = {r['date']: r for r in expansion['history']}
        self.assertEqual(len(result['history']), len(inputs))
        for row in [*result['history'], result['latest']]:
            live = 'issueDate' in row
            date = row.get('issueDate', row.get('date'))
            original = expansion['latest'] if live else inputs[date]
            self.assertEqual(row['probability'], original['probability'])
            fit = 0.2 if live else 0.35 * (int(date[:4]) - 1999)
            trail = []
            for lag in (3, 2, 1):
                source = inputs.get(month_offset(date, -lag))
                actual = row[f'lag{lag}Probability']
                if source is None:
                    self.assertIsNone(actual)
                else:
                    self.assertAlmostEqual(actual, risk(source['slope'], fit))
                trail.append(actual)
            expected = decisions([*trail, row['probability']])
            self.assertTrue(all(row[k] == v for k, v in expected.items()))
        january = next(r for r in result['history'] if r['date'] == '2000-01-01')
        self.assertNotAlmostEqual(january['lag1Probability'], inputs['1999-12-01']['probability'])
        live = result['latest']
        self.assertNotAlmostEqual(live['probability'], result['history'][-1]['probability'])
        self.assertEqual([v['date'] for v in live['path']], [month_offset(live['issueDate'], j) for j in range(-3, 1)])
        for v in live['path']:
            self.assertEqual(v['featureDate'], month_offset(v['date'], -2))
            self.assertEqual(set(v['features']), set(COMPLETE_CASE))
            self.assertAlmostEqual(v['probability'], risk(inputs[v['date']]['slope'], 0.2))

    def test_missing_exact_calendar_month_and_incomplete_inputs_only_disable_overlay(self):
        expansion, labels = fixture()
        # Remove the previous month entirely and leave a different lag's claims input missing.
        latest, removed = expansion['latest'], expansion['history'][-2]
        expansion['history'].remove(removed)
        for window in expansion['metrics'].values():
            window['n'] -= 1
        expansion['history'][-2]['claimsGrowth12'] = None
        expansion['history'][-2]['commonMature'] = False
        expansion['history'][-2]['probability'] = None
        for window in expansion['metrics'].values():
            window['n'] -= 1
        live = build_pace_trial(expansion, labels)['latest']
        self.assertEqual([v['probability'] is None for v in live['path']], [False, True, True, False])
        self.assertEqual(live['probability'], latest['probability'])
        self.assertFalse(live['paceAvailable'])
        self.assertIsNone(live['change3m'])
        self.assertTrue(all(live[field] == (live['probability'] >= .30) for field in ALERTS.values()))
        latest.update(available=False, probability=None, reason='Upstream comparison unavailable')
        absent = build_pace_trial(expansion, labels)['latest']
        self.assertFalse(absent['available'])
        self.assertTrue(all(absent[field] is None for field in ALERTS.values()))

    def test_same_sample_proper_scores_counts_and_distinct_episode_timing(self):
        expansion, labels = fixture()
        result = build_pace_trial(expansion, labels)
        for name, window in result['windows'].items():
            rows = [r for r in result['history'] if r['commonMature'] and window['windowStart'] <= r['date'] <= window['windowEnd']]
            independent = metrics([r['target'] for r in rows], [r['probability'] for r in rows])
            self.assertEqual(window['probabilityScores'], independent)
            self.assertEqual(window['n'], len(rows))
            episode, = window['episodes']
            for key, field in ALERTS.items():
                pre = [r for r in rows if r['target'] == 1 and r[field]]
                quiet = [r for r in rows if r['target'] == 0 and r[field]]
                if key != 'level':
                    changed = window['changes'][key]
                    self.assertEqual(changed['quietDates'], [r['date'] for r in quiet if not r['levelAlert']])
                    self.assertEqual(changed['preOnsetDates'], [r['date'] for r in pre if not r['levelAlert']])
                self.assertEqual(window['summary'][key]['quietAlerts'], len(quiet))
                self.assertEqual(window['summary'][key]['preOnsetAlerts'], len(pre))
                self.assertEqual(episode['methods'][key]['firstAlertDate'], pre[0]['date'] if pre else None)
                for r in rows:
                    self.assertLessEqual(r['levelAlert'], r['monthAlert'])
                    self.assertLessEqual(r['monthAlert'], r['quarterAlert'])
            for key in ('quarter', 'month'):
                gate = result['gate'][key]
                if gate['passed']:
                    self.assertTrue(gate['earlierAny'] and gate['maintainedHitsBoth'])
                    self.assertFalse(window['changes'][key]['quietDates'])

    def test_case_componentwise_dominance_is_descriptive_and_requires_known_advance(self):
        case = dict(date=CASE_DATE, probability=.25, change1m=.03, change3m=.09, quarterAlert=True,
                    levelAlert=False, paceAvailable=True, target=1, commonMature=True, onsetDate=CASE_ONSET)
        quiet = dict(case, date='2019-02-01', target=0)
        episode = dict(onsetDate=CASE_ONSET, coverage='full', methods={
            'level': {'leadMonths': 10}, 'quarter': {'firstAlertDate': CASE_DATE, 'leadMonths': 11},
        })
        extra = [dict(quiet, **{k: case[k] - .0001}) for k in ['probability', 'change1m', 'change3m']]
        extra.extend([dict(quiet, levelAlert=True), dict(quiet, paceAvailable=False), dict(quiet, target=1)])
        report = case_comparison(case, [quiet, *extra], [episode])
        self.assertTrue(report['available'])
        self.assertEqual(report['matches'], [{k: quiet[k] for k in ['date', 'probability', 'change1m', 'change3m']}])
        self.assertFalse(case_comparison(case, [quiet], [dict(episode, coverage='partial')])['available'])
        self.assertFalse(case_comparison(None, [quiet], [episode])['available'])
        self.assertFalse(case_comparison(dict(case, commonMature=False), [quiet], [episode])['available'])

    def test_rejects_stale_fits_and_feature_dates_and_empty_replay_is_inconclusive(self):
        expansion, labels = fixture()
        for field, value in [('featureDate', '2000-01-01'), ('probability', .8), ('expansionPriorProbability', .5)]:
            changed = copy.deepcopy(expansion)
            changed['latest'][field] = value
            with self.assertRaises(ValueError):
                build_pace_trial(changed, labels)
        expansion['history'] = []
        expansion['folds'] = []
        for window in expansion['metrics'].values():
            window.update(windowStart=None, windowEnd=None, n=0, models={'candidate': dict(brier=None, auc=None, logLoss=None)})
        result = build_pace_trial(expansion, labels)
        self.assertFalse(result['latest']['paceAvailable'])
        self.assertTrue(all(not v['passed'] for v in result['gate'].values()))
        self.assertIsNone(result['windows']['all']['probabilityScores']['brier'])


if __name__ == '__main__':
    unittest.main()
