import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import requests

from path_calibration import Calibration, LEGS, _daily_pairs, draw_shocks, monthly_offsets, prepare_calibration


def complete_month(start):
    days = pd.bdate_range(start, pd.Period(start, freq='M').end_time.normalize())
    return pd.DataFrame({LEGS[0]: np.linspace(1.0, 1.2, len(days)),
                         LEGS[1]: np.linspace(2.5, 2.08, len(days))}, index=days)


def numbered_bank(months):
    # The differences identify the precise donor month and prove that the pair stayed intact.
    a = np.array(months.asi8, dtype=float)
    frame = pd.DataFrame(dict(zip(LEGS, (a, -a))), index=months)
    return Calibration(frame, {})


class TreasuryTimingCalibrationTests(unittest.TestCase):
    def test_one_session_offset_matches_actual_equal_count_means_and_excludes_unfinished_month(self):
        jan, feb, mar = map(complete_month, ['2000-01-01', '2000-02-01', '2000-03-01'])
        feb.iloc[-1] = [1.52, 2.01]
        feb.iloc[3, 0] = np.nan
        all_days = pd.concat([jan, feb, mar]).rename_axis('observation_date').reset_index()
        pairs = _daily_pairs(all_days)
        offsets, _ = monthly_offsets(pairs, '2000-03-28')
        self.assertEqual(list(offsets.index.astype(str)), ['2000-02'])
        valid = feb.dropna()
        truth = (pd.concat([jan.tail(1), valid.iloc[:-1]]).mean()-valid.mean()) * 100
        np.testing.assert_allclose(offsets.iloc[0], truth, atol=1e-11)
        self.assertEqual(len(valid), len(feb)-1)

    def test_gap_in_quotes_disallows_donor_across_the_gap_and_short_month(self):
        months = [complete_month('2000-01-01'), complete_month('2000-03-01'),
                  complete_month('2000-04-01'), complete_month('2000-05-01').tail(9),
                  complete_month('2000-06-01'), complete_month('2000-07-01')]
        offsets, _ = monthly_offsets(pd.concat(months), '2000-07-20')
        self.assertEqual(list(offsets.index.astype(str)), ['2000-04'])

    def test_calibration_moments_cut_off_before_forecast_month(self):
        periods = pd.PeriodIndex(['2000-01','2000-02','2000-03','2001-03','2001-04'], freq='M')
        bank = numbered_bank(periods)
        bank.shocks = bank.shocks.copy()
        bank.shocks[-1] = [500, -624]
        summary = bank.summary('2001-04-01')
        self.assertEqual(summary['n'], 4)
        self.assertEqual(summary['end'], '2001-03-01')
        self.assertAlmostEqual(summary['correlation'], -1)
        self.assertAlmostEqual(summary['shortLag1'], 1)
        self.assertEqual(summary['within5'], 0)
        self.assertAlmostEqual(summary['covarianceBp2'], np.cov(bank.shocks[:4].T)[0, 1])
        before = bank.summary('1999-01')
        self.assertIsNone(before['start'])
        self.assertEqual(before['n'], 0)
        self.assertIsNone(before['within3'])

    def test_sampler_preserves_joint_quotes_block_adjacency_and_asof_cutoffs(self):
        months = pd.period_range('1980-01', '1996-12', freq='M').delete([15, 16, 49])
        bank = numbered_bank(months)
        dates = pd.period_range('1990-01','1994-01', freq='M')
        sample = draw_shocks(bank, dates, n=100, seed=657, block_months=6)
        comparison = draw_shocks(bank, dates[:14], n=100, seed=657, block_months=6)
        np.testing.assert_array_equal(sample[:14], comparison)
        np.testing.assert_array_equal(sample[:,:,0], -sample[:,:,1])
        self.assertTrue((sample[:,:,0] < dates.asi8[:, None]).all())
        self.assertTrue(np.isin(sample[:,:,0],months.asi8).all())
        for history in sample[:,:,0].T:
            # Cuts can coincide with a natural continuation. Every detectable internal
            # break must nevertheless occur in the same position modulo block length.
            breaks = np.flatnonzero(np.diff(history) != 1) + 1
            self.assertGreater(len(breaks), 1)
            self.assertTrue((np.diff(breaks) % 6 == 0).all())
        bank.shocks = bank.shocks.copy()
        bank.shocks[months >= dates[-1], :] = 100000
        same = draw_shocks(bank, dates, n=100, seed=657, block_months=6)
        np.testing.assert_array_equal(same, sample)

    def test_first_anchor_requires_an_entire_prior_donor_block(self):
        months = pd.period_range('2000-01', '2003-01',freq='M')
        bank = numbered_bank(months)
        with self.assertRaisesRegex(ValueError, 'before'):
            draw_shocks(bank, [pd.Period('2000-06', freq='M')], 15, 0, 6)
        shocks = draw_shocks(bank, [pd.Period('2000-07',freq='M')], 15, 0, 6)
        self.assertTrue(np.isin(shocks[0,:,0], months[:6].asi8).all())

    def test_bad_direct_response_or_outage_keeps_validated_source_and_reports_cached_end(self):
        # More than 6,500 common observations satisfy the source-history check.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'research/raw/treasury-daily.csv'
            path.parent.mkdir(parents=True)
            dates = pd.bdate_range('1962-01-02','1989-12-28')
            frame = pd.DataFrame({LEGS[0]: 2.5, LEGS[1]: 3.2}, index=dates)
            frame.to_csv(path, index_label='observation_date')
            before = path.read_bytes()
            def unavailable(*args, **kwargs):
                raise requests.Timeout('Provider unavailable')
            with patch.dict(os.environ, {'FRED_API_KEY': ''}):
                c = prepare_calibration(True, root=folder, as_of='1989-12-28', get=unavailable)
            self.assertEqual(c.provenance['mode'], 'dated-cache')
            self.assertEqual(c.provenance['dailyEnd'], '1989-12-28')
            self.assertEqual(c.provenance['donorEnd'], '1989-11-01')
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
