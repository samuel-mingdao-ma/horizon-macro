import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import build_model as engine
from build_model import complete_monthly_claims
from provider_fallback import parse_fred_csv


class LeadingFeedTests(unittest.TestCase):
    def test_only_complete_calendar_months_are_averaged(self):
        dates = pd.date_range('2020-01-04', '2020-04-18', freq='W-SAT')
        series = pd.Series(range(len(dates)), index=dates, dtype=float)
        series = series.drop(pd.Timestamp('2020-02-01'))
        series.loc['2020-03-21'] = float('nan')
        monthly = complete_monthly_claims(series, pd.Timestamp('2020-04-01'))
        self.assertEqual(monthly.index[-1], pd.Timestamp('2020-03-01'))
        self.assertAlmostEqual(monthly['2020-01-01'], 1.5)
        self.assertTrue(pd.isna(monthly['2020-02-01']))
        self.assertTrue(pd.isna(monthly['2020-03-01']))

    def test_optional_outage_preserves_original_receipt_date_and_core_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / 'research' / 'raw'
            raw.mkdir(parents=True)
            (root / 'data').mkdir()
            previous_date = '2026-10-08T13:30:00Z'
            prior = {'ICSA': {'sourceRetrievedAt': previous_date, 'verifiedProviderLastDate': '2026-10-03'}}
            (root / 'data/snapshot.json').write_text(
                json.dumps({'meta': {'dataRefresh': {'perSeries': prior}}})
            )
            (raw / 'ICSA.csv').write_text('observation_date,ICSA\n2026-10-03,210000\n')

            class Response:
                text = 'observation_date,GS10\n2026-10-01,4.0\n'

                def raise_for_status(self):
                    pass

            def fetch(url, **kwargs):
                if url.endswith('id=ICSA'):
                    raise OSError('fixture outage')
                return Response()

            feeds = {key: engine.SERIES[key] for key in ('ICSA', 'GS10')}
            with patch.object(engine, 'ROOT', root), patch.object(engine, 'RAW', raw), patch.object(
                engine, 'SERIES', feeds
            ), patch.dict(engine.os.environ, {'FRED_API_KEY': ''}), patch.object(
                engine.requests, 'get', side_effect=fetch
            ):
                values, meta = engine.load_dataset(True)
            self.assertEqual(values['ICSA'].iloc[-1], 210000)
            self.assertEqual(meta['mode'], 'mixed-direct-and-cache')
            self.assertEqual(meta['perSeries']['ICSA']['sourceRetrievedAt'], previous_date)
            self.assertFalse(meta['perSeries']['ICSA']['refreshed'])
            self.assertTrue(meta['perSeries']['GS10']['refreshed'])

    def test_claims_date_validation_and_monthly_permits(self):
        with self.assertRaisesRegex(ValueError, 'Saturdays'):
            parse_fred_csv('observation_date,ICSA\n2020-01-03,10\n', 'ICSA')
        with self.assertRaisesRegex(ValueError, 'month starts'):
            parse_fred_csv('observation_date,PERMIT\n2020-01-03,10\n', 'PERMIT')
        self.assertEqual(parse_fred_csv('observation_date,ICSA\n2020-01-04,10\n', 'ICSA').iloc[0], 10)


if __name__ == '__main__':
    unittest.main()
