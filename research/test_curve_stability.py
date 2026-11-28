"""Check neutral bands, exact ratio boundaries, continuous stress and paired onset evaluation."""

import copy
import unittest
from fractions import Fraction

from curve_stability import BANDS, GRID, RATIOS, REFERENCE, build_curve_stability_trial, evaluate_cell, stability_csv_rows
from forecast_ledger import month_offset


def synthetic_parent():
    months = {}
    for onset in ('2001-04-01', '2020-03-01'):
        for lead in range(12, 0, -1):
            date = month_offset(onset, -lead)
            level = not (onset == '2001-04-01' and lead > 10)
            months[date] = (onset, level)
    months['2019-02-01'] = (None, False)
    history = []
    for date, (onset, level) in sorted(months.items()):
        may, feb = date == '2000-05-01', date == '2019-02-01'
        history.append(dict(
            date=date, featureDate=month_offset(date,-2), lagFeatureDate=month_offset(date,-5),
            shortChange=.49 if may else .24 if feb else .01, longChange=-.02 if may else -.17 if feb else 0,
            levelAlert=level, quarterAlert=level or may or feb, mixedTwoToOneAlert=level or may,
            probability=.4 if level else .25, commonMature=True,
            issuePhase='pre-onset' if onset else 'expansion-no-recession', target=int(bool(onset)), onsetDate=onset,
        ))
    latest = dict(history[-1], issueDate=history[-1]['date'], available=True, reason=None, refitDate=history[-1]['date'],
                  forecastStart='2020-03-01', forecastEnd='2021-02-01')
    windows = {}
    for label, sample in [('all', history), ('rolling120', [r for r in history if r['date'] >= '2019-02-01'])]:
        onsets = sorted({r['onsetDate'] for r in sample if r['onsetDate']})
        episodes = []
        for onset in onsets:
            rows = [r for r in sample if r['onsetDate'] == onset]
            first = next(r['date'] for r in rows if r['levelAlert'])
            lead = 10 if onset == '2001-04-01' else 12
            episodes.append(dict(onsetDate=onset, coverage='full', availableMonths=len(rows),
                                 methods={'level': dict(leadMonths=lead, firstAlertDate=first)}))
        windows[label] = dict(windowStart=sample[0]['date'], windowEnd=sample[-1]['date'], n=len(sample),
                              quietExpansionN=1, preOnsetN=len(sample)-1, completeEpisodes=len(episodes), episodes=episodes,
                              probabilityScores=dict(brier=.11, logLoss=.36, auc=.8),
                              summary={'level': dict(completeHits=len(episodes), quietAlerts=0,
                                                     preOnsetAlerts=sum(r['levelAlert'] for r in sample))})
    return dict(history=history, latest=latest, windows=windows)


class StabilityTests(unittest.TestCase):
    def test_ratio_edges_deadband_raw_flattening_and_missing(self):
        # The upper bound is open when the bill's change is inside the symmetric band.
        for s,l,d,r,expected in [
            (.035, -.02, 0, 1.75, True), (.035,-.020000000001,0,1.75,False),
            (.02,-.05,5,2,True), (.02,-.050000000001,5,2,False), (.02,.02,5,2,False),
            (.03,.02,2,2.5,True), (.03,.020000000001,2,2.5,False),
            (0,-.02,5,2,False), (-.01,-.08,2,2,False),
        ]:
            self.assertEqual(evaluate_cell(s,l,False,True,d,r)['actual'],expected,(s,l,d,r))
        open_edge = evaluate_cell(.02,.05,False,True,5,2)
        self.assertFalse(open_edge['upperInclusive'])
        self.assertFalse(open_edge['possible'])  # stress interval starts exactly at the excluded ceiling
        for s,l in ((None,.01),(.01,None)):
            for level,quarter,expected in ((False,True,False),(True,True,True),(False,False,False),(None,None,None)):
                result = evaluate_cell(s,l,level,quarter,5,2)
                self.assertTrue(all(result[k] is expected for k in ('actual','guaranteed','possible','minus3','plus3')))
        with self.assertRaisesRegex(ValueError,'Inconsistent'):
            evaluate_cell(.49,-.02,True,False,5,2)
        with self.assertRaisesRegex(ValueError,'Unregistered'):
            evaluate_cell(.49,-.02,False,True,4,2)

    def test_possible_detects_intersection_with_no_endpoint_or_observed_alert(self):
        result = evaluate_cell(.005,.01,False,True,0,2)
        self.assertEqual((result['lowerBp'], result['upperBp']), (-.25,0))
        self.assertTrue(result['possible'])
        self.assertFalse(any(result[k] for k in ('guaranteed','actual','minus3','plus3')))

    def test_continuous_stress_agrees_with_independent_piecewise_filter(self):
        # Evaluate the original filter at its breakpoints and inside every resulting segment.
        for s in map(Fraction,['-2','0','1/4','2','8','24']):
            for l in map(Fraction,['-17','-9/2','-2','0','1','5','8']):
                for band in BANDS:
                    for ratio in RATIOS:
                        r = Fraction(ratio)
                        def direct(x):
                            effective = 0 if abs(x) <= band else x
                            return s > 0 and s-x > 0 and effective <= 0 and s >= -r*effective
                        points = sorted({x for x in (l-3,l+3,l,-band,band,0,s,-s/r) if l-3 <= x <= l+3})
                        samples = [*points,*[(a+b)/2 for a,b in zip(points,points[1:])]]
                        vals = [direct(x) for x in samples]
                        result = evaluate_cell(float(s/100),float(l/100),False,True,band,ratio)
                        self.assertEqual((result['actual'],result['guaranteed'],result['possible']),
                                         (direct(l),all(vals),any(vals)), (s,l,band,ratio))

    def test_paired_grid_checks_actual_2001_advance_and_opposite_tail_for_quiet_months(self):
        parent = synthetic_parent()
        t = build_curve_stability_trial(parent)
        self.assertEqual(len(t['cells']),20)
        self.assertEqual(sum(c['pointPassed'] for c in t['cells']),20)
        passing = {c['id'] for c in t['cells'] if c['stressPassed']}
        self.assertEqual(passing,{key for key,d,r in GRID if d > 0 and r >= 1.75})
        ref = next(c for c in t['cells'] if c['id'] == REFERENCE)
        self.assertEqual(ref['windows']['all']['guaranteedPreDates'],['2000-05-01'])
        self.assertEqual(ref['windows']['all']['episodes'][0]['guaranteedLead'],11)
        self.assertEqual(ref['windows']['rolling120']['episodes'][0]['guaranteedLead'],12)
        self.assertEqual(t['windows']['all']['probabilityScores'],parent['windows']['all']['probabilityScores'])
        self.assertEqual(t['latest']['probability'],parent['latest']['probability'])
        sensitivity = next(c for c in t['cells'] if c['id'] == 'd2-r1.5')
        self.assertFalse(sensitivity['stressPassed'])
        for period in ('all','rolling120'):
            self.assertEqual(sensitivity['windows'][period]['possibleQuietDates'],['2019-02-01'])
            self.assertFalse(sensitivity['windows'][period]['actualQuietDates'])
        records = list(stability_csv_rows(t))
        self.assertEqual(len(records),len(parent['history'])*20)
        for row in records:
            if row['cellId'] == 'd0-r2':
                self.assertIs(row['actual'],row['mixedTwoToOneAlert'])
            self.assertLessEqual(row['guaranteed'],row['actual'])
            self.assertLessEqual(row['actual'],row['possible'])
        # The reference must not pass without actual evidence at the known forecast origin.
        missing = copy.deepcopy(parent)
        may = next(r for r in missing['history'] if r['date'] == '2000-05-01')
        may.update(shortChange=None,mixedTwoToOneAlert=False)
        self.assertFalse(any(c['pointPassed'] for c in build_curve_stability_trial(missing)['cells']))

    def test_reject_regressive_or_mismatched_baseline(self):
        for key,mutate in [('control',lambda p: p['history'][1].update(mixedTwoToOneAlert=False)),
                           ('mature',lambda p: p['windows']['rolling120'].update(n=0)),
                           ('unique',lambda p: p['history'].append(p['history'][-1]))]:
            p = synthetic_parent()
            mutate(p)
            with self.assertRaisesRegex(ValueError,key):
                build_curve_stability_trial(p)


if __name__ == '__main__':
    unittest.main()
