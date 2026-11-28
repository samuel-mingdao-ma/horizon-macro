import math
import unittest
from itertools import product

from forecast_ledger import month_offset
from joint_stress import Issue, _issue, _risk
from pace_trial import decisions


def case(base, beta=-2, short=40, long=-10):
    prior = 0.1
    logits = []
    for risk in base:
        sig = None if risk is None else 2 * risk - prior
        logits.append(None if sig is None else math.log(sig / (1 - sig)))
    return Issue(base, prior, beta, short, long, logits)


class JointStressTests(unittest.TestCase):
    def test_interior_alert_is_missed_even_by_all_corner_and_neutral_endpoints(self):
        issue = case([0.27, 0.29, 0.312, 0.30])
        ternary_states = {
            issue.point(ends, previous)[0]
            for ends in product((-3, 0, 3), repeat=4)
            for previous in product((-3, 0, 3), repeat=2)
        }
        self.assertEqual(ternary_states, {'off', 'level'})
        outcome = issue.stress(3, capture=True)
        self.assertTrue(outcome['certified'])
        self.assertEqual(outcome['extra'], [False, True])
        proof = outcome['witnesses']['extra']
        self.assertEqual(issue.full_point(proof['shocksBp']), ('extra', proof))
        self.assertGreater(proof['change1m'], 0)
        self.assertLess(proof['probability'], 0.30)

    def test_slope_shift_reprices_lagged_vectors_and_preserves_equal_shifts(self):
        issue = case([0.16, 0.18, 0.20, 0.255], short=49, long=-2)
        _, neutral = issue.full_point([(0, 0)] * 4)
        _, shifted = issue.full_point([(3, 3), (-1, -1), (2, 2), (3, 3)])
        self.assertEqual(neutral['path'], shifted['path'])
        _, repriced = issue.full_point([(0, -5), (-2, 3), (4, -1), (0, 5)])
        expected = [
            _risk(z + issue.beta * (long - short) / 100, issue.prior)
            for z, (short, long) in zip(issue.logits, repriced['shocksBp'])
        ]
        self.assertEqual(repriced['path'], expected)
        for key in ('change1m', 'change3m', 'levelAlert', 'quarterAlert'):
            self.assertEqual(repriced[key], decisions(expected)[key])
        self.assertEqual(repriced['longChangeBp'], 8)
        self.assertFalse(repriced['referenceAlert'])
        self.assertTrue(repriced['quarterAlert'])
        self.assertEqual(repriced['shortChangeBp'], 49)

    def test_certificates_enclose_arbitrary_fractional_moves_with_both_coefficient_signs(self):
        import random

        rng = random.Random(18)
        for beta in (-1.5, 1.5, 0):
            issue = case([0.16, 0.19, 0.218, 0.289], beta=beta, short=24, long=-17)
            radius = 5
            band = issue.stress(radius)
            self.assertTrue(band['certified'])
            for _ in range(75):
                shocked = [[rng.uniform(-radius, radius), rng.uniform(-radius, radius)] for _ in range(4)]
                state, result = issue.full_point(shocked)
                for field in ('probability', 'change1m', 'change3m'):
                    self.assertLessEqual(band[field][0], result[field])
                    self.assertGreaterEqual(band[field][1], result[field])
                for field, value in [
                    ('level', state == 'level'),
                    ('alert', state != 'off'),
                    ('extra', state == 'extra'),
                ]:
                    self.assertLessEqual(band[field][0], value)
                    self.assertGreaterEqual(band[field][1], value)

    def test_missing_midpoint_or_yield_blocks_only_the_extra_alarm(self):
        for issue in [case([0.16, None, 0.20, 0.305]), case([0.16, 0.18, 0.20, 0.305], long=None)]:
            out = issue.stress(3, capture=True)
            self.assertTrue(out['certified'])
            self.assertEqual(out['extra'], [False, False])
            self.assertEqual(out['alert'], out['level'])
            self.assertEqual(out['alert'], [False, True])
            self.assertIsNotNone(out['change1m'][0])
        self.assertEqual(case([0.16, None, 0.20, 0.305]).stress(3)['change3m'], [None, None])
        missing = case([0.16, 0.18, 0.20, None]).stress(3, capture=True)
        self.assertTrue(
            all(
                missing[k] == [None, None]
                for k in ('level', 'alert', 'extra', 'probability', 'change1m', 'change3m')
            )
        )
        self.assertTrue(all(p is None for p in missing['witnesses'].values()))

    def test_saturated_p_can_reprice_from_finite_log_odds(self):
        issue = Issue([0.55] * 4, 0.1, -10, 20, -5, [40] * 4)
        self.assertEqual(issue.risk(3, 0), 0.55)
        self.assertEqual(issue.risk(3, 400), 0.30)

    def test_validates_issue_clock_and_checks_fitted_probability_for_each_lag(self):
        date = '2000-05-01'
        model = dict(
            refitDate='2000-01-01',
            trainingPrevalence=0.1,
            coefficients=[1],
            scales=[1],
            means=[2],
            featureOrder=['slope'],
            intercept=0,
        )
        months = [month_offset(date, lag) for lag in (-3, -2, -1, 0)]
        origins = {m: dict(date=m, featureDate=month_offset(m, -2), slope=i * 0.5) for i, m in enumerate(months)}
        base = [_risk(r['slope'] - 2, 0.1) for r in origins.values()]
        origin = origins[date]
        origin.update(
            probability=base[-1],
            refitDate=model['refitDate'],
            expansionPriorProbability=0.1,
            commonMature=True,
            issuePhase='pre-onset',
            target=1,
            onsetDate='2001-04-01',
        )
        pace = dict(
            origin, lag1Probability=base[2], lag2Probability=base[1], lag3Probability=base[0], **decisions(base)
        )
        legs = dict(origin, lagFeatureDate=month_offset(date, -5), shortChange=0.49, longChange=-0.02)
        _, issue = _issue(origin, pace, legs, model, origins)
        self.assertAlmostEqual(issue.risk(3, 6), _risk(origin['slope'] - 2 + 0.06, 0.1))
        origins[months[0]]['slope'] += 1
        with self.assertRaisesRegex(ValueError, 'frozen fit'):
            _issue(origin, pace, legs, model, origins)
        origins[months[0]]['featureDate'] = date
        with self.assertRaisesRegex(ValueError, 'release lag'):
            _issue(origin, pace, legs, model, origins)


if __name__ == '__main__':
    unittest.main()
