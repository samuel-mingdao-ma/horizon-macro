"""Empirical monthly Treasury timing offsets and chronological paired-block sampling."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import StringIO
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
LEGS = ['DTB3', 'DGS10']
SOURCE_URLS = [f'https://fred.stlouisfed.org/series/{s}' for s in LEGS]
GRAPH_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10,DTB3&cosd=1962-01-01'
API_URL = 'https://api.stlouisfed.org/fred/series/observations'
HEADERS = {'User-Agent': 'Horizon-Macro-Research/1.0'}


def _daily_pairs(frame):
    if not {'observation_date', *LEGS}.issubset(frame):
        raise ValueError('Expected dated H.15 bill and ten-year daily yields')
    dates = pd.DatetimeIndex(pd.to_datetime(frame['observation_date'], format='%Y-%m-%d', errors='raise'))
    if dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError('Daily observations require distinct, chronological dates')
    quotes = frame[LEGS].replace({'.': np.nan, '': np.nan}).apply(pd.to_numeric, errors='raise')
    quotes.index = dates
    pairs = quotes.dropna().astype(float)
    if pairs.empty or not np.isfinite(pairs.to_numpy()).all() or (pairs.index.dayofweek >= 5).any():
        raise ValueError('Expected finite, paired Treasury quotes dated on business days')
    return pairs


def _fetch_daily(get):
    token = os.environ.get('FRED_API_KEY', '').strip()
    if token:
        def fetch_leg(series):
            response = get(API_URL, params={'series_id': series, 'api_key': token, 'file_type': 'json',
                'observation_start': '1962-01-01', 'limit': 100000}, timeout=20, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            obs = data['observations']
            if not obs or int(data['count']) != len(obs):
                raise ValueError('Incomplete Treasury source response')
            values = pd.DataFrame(obs)[['date', 'value']].rename(columns={'date': 'observation_date', 'value': series})
            return values
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                short, long = list(pool.map(fetch_leg, LEGS))
            frame = short.merge(long, how='outer', on='observation_date', validate='one_to_one', sort=True)
            return _daily_pairs(frame), 'fred-api'
        except (requests.RequestException, KeyError, TypeError, ValueError):
            # Request exceptions may contain a credential-bearing URL.
            pass
    response = get(GRAPH_URL, timeout=12, headers=HEADERS)
    response.raise_for_status()
    frame = pd.read_csv(StringIO(response.text), na_values=['.', ''])
    return _daily_pairs(frame), 'fred-direct'


def _check_history(new, old):
    if new.index[0] > pd.Timestamp('1962-02-01') or len(new) < 6500:
        raise ValueError('Daily calibration source lacks the pre-evaluation history')
    if old is not None and (
        new.index[0] > old.index[0] or new.index[-1] < old.index[-1] or len(new) < int(0.99 * len(old))
    ):
        raise ValueError('Truncated daily calibration source')


class Calibration:
    def __init__(self, offsets, provenance):
        if not isinstance(offsets.index, pd.PeriodIndex) or offsets.index.freqstr != 'M':
            raise ValueError('Monthly calibration donors require a monthly PeriodIndex')
        if offsets.index.has_duplicates or not offsets.index.is_monotonic_increasing or offsets.empty:
            raise ValueError('Calibration donors must be nonempty distinct chronological months')
        self.months = offsets.index
        self.shocks = offsets[LEGS].to_numpy(dtype=float)
        if not np.isfinite(self.shocks).all():
            raise ValueError('Missing Treasury offsets cannot enter the sampling bank')
        self.provenance = provenance

    def summary(self, cutoff):
        stop = self.months.searchsorted(pd.Period(cutoff, freq='M'), side='left')
        values = self.shocks[:stop]
        fields = ('shortSdBp', 'longSdBp', 'shortMeanBp', 'longMeanBp', 'shortMedianAbsBp', 'longMedianAbsBp',
                  'shortP90AbsBp', 'longP90AbsBp', 'correlation', 'covarianceBp2', 'shortLag1', 'longLag1',
                  'within3', 'within5')
        report = {k: None for k in fields}
        report.update(cutoff=_date(pd.Period(cutoff, freq='M')), start=_date(self.months[0]) if stop else None,
                      end=_date(self.months[stop-1]) if stop else None, n=int(stop))
        if not stop:
            return report
        for radius in [3, 5]:
            report[f'within{radius}'] = float((np.abs(values).max(axis=1) <= radius).mean())
        adjacent = np.diff(self.months[:stop].asi8) == 1
        for i, leg in enumerate(['short', 'long']):
            x = values[:, i]
            report[leg+'MeanBp'] = float(x.mean())
            report[leg+'MedianAbsBp'], report[leg+'P90AbsBp'] = np.quantile(np.abs(x), [.5, .9]).tolist()
            if stop >= 2:
                report[leg+'SdBp'] = float(x.std(ddof=1))
                report[leg+'Lag1'] = _correlation(x[:-1][adjacent], x[1:][adjacent])
        if stop >= 2:
            report['correlation'] = _correlation(values[:, 0], values[:, 1])
            report['covarianceBp2'] = float(np.cov(values.T, ddof=1)[0, 1])
        return report


def _correlation(x, y):
    if len(x) < 2 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _date(period):
    return period.start_time.strftime('%Y-%m-%d')


def monthly_offsets(pairs, as_of):
    """Move each common-day quote window one trading session earlier, holding its count fixed."""
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is not None:
        as_of = as_of.tz_convert('UTC').tz_localize(None)
    paired = pairs.loc[:as_of.normalize(), LEGS]
    if paired.empty:
        raise ValueError('No daily yield pairs are available as of the requested date')
    groups = paired.groupby(paired.index.to_period('M'))
    last = groups.last()
    counts = groups.size()
    # The difference of equal-count means simplifies to the two endpoints divided by N.
    # Rounding only eliminates floating-point artifacts from the quoted hundredths of a percent.
    delta = (last.shift(1) - last).mul(100).div(counts, axis=0).round(12)
    contiguous = np.r_[False, np.diff(last.index.asi8) == 1]
    # Both monthly endpoints need usable coverage. Observing a quote in the next month
    # establishes that the last source month used here was finished at this vintage.
    complete = (counts >= 15) & (counts.shift(1) >= 15) & contiguous & (last.index < last.index[-1])
    return delta.loc[complete], paired


def prepare_calibration(refresh=False, root=None, as_of=None, get=None):
    path = (Path(root) if root is not None else ROOT) / 'research/raw/treasury-daily.csv'
    quotes = _daily_pairs(pd.read_csv(path, na_values=['.', ''])) if path.exists() else None
    if quotes is not None:
        _check_history(quotes, None)
    mode = 'bundled-cache'
    if refresh or quotes is None:
        try:
            new, provider = _fetch_daily(get or requests.get)
            _check_history(new, quotes)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            if quotes is None:
                raise ValueError('Could not obtain the daily historical calibration source') from None
            mode = 'dated-cache'
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile('w', dir=path.parent, delete=False) as tmp:
                staged = Path(tmp.name)
                try:
                    new.to_csv(tmp, index_label='observation_date', float_format='%.2f')
                except BaseException:
                    staged.unlink(missing_ok=True)
                    raise
            staged.replace(path)
            quotes, mode = new, provider
    offsets, pairs = monthly_offsets(quotes, as_of if as_of is not None else datetime.now(timezone.utc))
    if offsets.empty:
        raise ValueError('No eligible complete-month Treasury timing offsets')
    facts = dict(mode=mode, series=list(LEGS), urls=list(SOURCE_URLS),
        dailyStart=pairs.index[0].strftime('%Y-%m-%d'), dailyEnd=pairs.index[-1].strftime('%Y-%m-%d'),
        pairedDays=len(pairs), donorStart=_date(offsets.index[0]), donorEnd=_date(offsets.index[-1]), donorMonths=len(offsets),
        method='Difference in an equal-count monthly mean from moving the common daily Treasury quote window one trading session earlier. Replace the last paired quote with the preceding calendar month’s last paired quote. Archive only actual joint observations and estimate timing sensitivity on completed months.')
    return Calibration(offsets, facts)


def draw_shocks(calibration, dates, n, seed, block_months):
    """Draw one chronological paired history per path. Donor blocks are fully in the past at entry."""
    periods = pd.PeriodIndex(dates, freq='M')
    if not len(periods) or n <= 0 or block_months <= 0 or np.any(np.diff(periods.asi8) != 1):
        raise ValueError('A positive path count, block length and consecutive simulated calendar months are required')
    months = calibration.months.asi8
    size = block_months
    if len(months) < size:
        raise ValueError('Insufficient calibration months for a full donor block')
    # Checking ordered endpoint distance also detects any gap inside the candidate block.
    starts = np.flatnonzero(months[size-1:] - months[:len(months)-size+1] == size-1)
    ends = months[starts + size - 1]
    rng = np.random.default_rng(seed)
    draws = np.empty((len(periods), n, 2), dtype=float)
    remaining = np.zeros(n, dtype=np.int32)
    cursor = np.zeros(n, dtype=np.int32)
    for t, month in enumerate(periods.asi8):
        new = np.flatnonzero(remaining == 0)
        if len(new):
            eligible = int(np.searchsorted(ends, month, side='left'))
            if eligible == 0:
                raise ValueError(f'No complete historical donor block before {periods[t]}')
            sampled = starts[rng.integers(eligible, size=len(new))]
            # Randomize initial phase across paths so calendar boundaries do not determine
            # where every simulated sequence breaks. Later blocks contain exactly size months.
            skip = rng.integers(size, size=len(new)) if t == 0 and size > 1 else 0
            cursor[new] = sampled + skip
            remaining[new] = size - skip
        draws[t] = calibration.shocks[cursor]
        cursor += 1
        remaining -= 1
    return draws
