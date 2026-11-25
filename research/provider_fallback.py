"""Official, keyless source fallback for the HORIZON research refresh.

FRED-MD contains the original level observations, not transformed model inputs.
The Chicago Fed's Credit column is the same series published as NFCICREDIT.
Unserved target/tenor series retain their dated cache; missing labels stay missing.
"""
from __future__ import annotations
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import re
from urllib.parse import urljoin
import concurrent.futures
import pandas as pd
import requests

FRED_MD_PAGE = 'https://www.stlouisfed.org/research/economists/mccracken/fred-databases'
CHICAGO_CREDIT_CSV = 'https://api.data.chicagofed.org/NFCI/nfci-data-series-csv.csv'
MD_SERIES = ['GS10', 'TB3MS', 'UNRATE', 'CPIAUCSL', 'FEDFUNDS', 'GS1', 'GS5']
CORE = ['GS10', 'TB3MS', 'UNRATE', 'NFCICREDIT']
HEADERS = {'User-Agent': 'Horizon-Macro-Research/1.0', 'Accept': 'text/csv,application/json,text/html'}


def last_date(series):
    valid = series.dropna()
    return valid.index[-1].strftime('%Y-%m-%d') if len(valid) else None


def parse_fred_csv(text, series_id):
    if not text.splitlines() or text.splitlines()[0].strip() not in [f'observation_date,{series_id}', f'DATE,{series_id}']:
        raise ValueError(f'{series_id}: unexpected FRED CSV format')
    frame = pd.read_csv(StringIO(text), na_values=['.', ''], index_col=0, parse_dates=True)
    result = pd.to_numeric(frame[series_id], errors='coerce')
    validate_series(result, series_id)
    return result


def validate_series(series, series_id):
    if not isinstance(series.index, pd.DatetimeIndex) or series.index.hasnans or series.index.has_duplicates or not series.index.is_monotonic_increasing:
        raise ValueError(f'{series_id}: invalid observation index')
    if series.dropna().empty:
        raise ValueError(f'{series_id}: no usable observations')
    if series_id != 'NFCICREDIT' and any(series.index.day != 1):
        raise ValueError(f'{series_id}: monthly observations must be month starts')
    return series


def latest_md_url(html):
    # The official page lists current.csv first; its href is the actual dated file.
    paths = re.findall(r'(?:href)=["\']([^"\']*/fred-md/monthly/[^"\']+\.csv(?:\?[^"\']*)?)["\']', html, flags=re.I)
    if not paths:
        raise ValueError('Official FRED-MD page contains no monthly data link')
    url = urljoin(FRED_MD_PAGE, paths[0].replace('&amp;', '&'))
    if not url.startswith('https://www.stlouisfed.org/'):
        raise ValueError('Unexpected FRED-MD data origin')
    return url


def parse_md_csv(text):
    frame = pd.read_csv(StringIO(text), na_values=['.', ''])
    if 'sasdate' not in frame or not all(s in frame for s in MD_SERIES):
        raise ValueError('Official FRED-MD columns missing')
    dates = pd.to_datetime(frame.sasdate, format='%m/%d/%Y', errors='coerce')
    # Excludes the transformation-code row, never applies its transformations.
    frame = frame.loc[dates.notna()].copy()
    frame.index = pd.DatetimeIndex(dates.loc[dates.notna()])
    result = {}
    for series_id in MD_SERIES:
        values = pd.to_numeric(frame[series_id], errors='coerce').rename(series_id)
        result[series_id] = validate_series(values, series_id)
    return result


def parse_chicago_credit(text):
    frame = pd.read_csv(StringIO(text), na_values=['.', ''])
    if not {'Friday_of_Week', 'Credit'}.issubset(frame.columns):
        raise ValueError('Official Chicago Fed credit columns missing')
    dates = pd.to_datetime(frame.Friday_of_Week, format='%m/%d/%Y', errors='raise')
    values = pd.Series(pd.to_numeric(frame.Credit, errors='coerce').to_numpy(), index=pd.DatetimeIndex(dates), name='NFCICREDIT')
    return validate_series(values, 'NFCICREDIT')


def merge_observations(cached, fetched, series_id):
    """New source revises overlapping dates; later cached dates are retained.

    Explicit NaNs from a published release remain NaNs. There is no ffill,
    interpolation, month skipping, or synthetic target-label extension.
    """
    if cached is None:
        return validate_series(fetched.copy(), series_id)
    joined = pd.concat([cached, fetched])
    joined = joined.loc[~joined.index.duplicated(keep='last')].sort_index()
    joined.name = series_id
    return validate_series(joined, series_id)


def _download(url, get):
    response = get(url, timeout=8, headers=HEADERS)
    response.raise_for_status()
    return response.text


def fetch_official_sources(get=requests.get, cache_dir=None):
    def md():
        url = latest_md_url(_download(FRED_MD_PAGE, get))
        text = _download(url, get)
        return parse_md_csv(text), url, text
    def credit():
        text = _download(CHICAGO_CREDIT_CSV, get)
        return parse_chicago_credit(text), text
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        md_job, credit_job = pool.submit(md), pool.submit(credit)
        md_data, md_url, md_text = md_job.result()
        credit_data, credit_text = credit_job.result()
    md_data['NFCICREDIT'] = credit_data
    urls = {s: md_url for s in MD_SERIES}
    urls['NFCICREDIT'] = CHICAGO_CREDIT_CSV
    if not all(s in md_data and not md_data[s].dropna().empty for s in CORE):
        raise ValueError('Required official fallback sources incomplete')
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / 'fred-md.csv').write_text(md_text)
        (cache_dir / 'chicago-credit.csv').write_text(credit_text)
    return md_data, urls


def previous_provenance(root):
    for path in [root / 'data' / 'snapshot.json', root / 'public' / 'data' / 'snapshot.json']:
        try:
            snapshot = json.loads(path.read_text())
            previous = snapshot.get('meta', {}).get('dataRefresh', {}).get('perSeries', {})
            for source in snapshot.get('sources', []):
                previous.setdefault(source['id'], {})
                previous[source['id']].setdefault('sourceRetrievedAt', source.get('retrievedAt'))
            return previous
        except (FileNotFoundError, ValueError, KeyError):
            continue
    return {}


def fallback_dataset(cached, original, direct_success=None, get=requests.get, checked_at=None, cache_dir=None):
    """Return a complete dataset only after both required official sources verify."""
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    direct_success = direct_success or {}
    fetched, urls = fetch_official_sources(get, cache_dir=cache_dir)
    output, provenance = {}, {}
    for series_id in cached.keys() | fetched.keys() | direct_success.keys():
        old = cached.get(series_id)
        original_time = original.get(series_id, {}).get('sourceRetrievedAt')
        if series_id in direct_success:
            values = direct_success[series_id]
            provider_url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
            mode, refreshed = 'fred-direct', True
        elif series_id in fetched:
            values = merge_observations(old, fetched[series_id], series_id)
            provider_url = urls[series_id]
            mode, refreshed = 'official-provider', True
        else:
            if old is None:
                raise ValueError(f'{series_id}: neither a verified provider nor a dated cache is available')
            values = old.copy()
            provider_url, mode, refreshed = None, 'dated-cache', False
        provider_values = direct_success.get(series_id, fetched.get(series_id))
        provider_last = last_date(provider_values) if provider_values is not None else None
        latest_from_cache = not refreshed or (provider_last is not None and last_date(values) > provider_last)
        source_time = original_time if latest_from_cache else checked_at
        output[series_id] = values
        provenance[series_id] = dict(mode=mode, fetchedUrl=provider_url, lastDate=last_date(values),
            verifiedProviderLastDate=provider_last, refreshed=refreshed,
            latestObservationFromCache=latest_from_cache, cacheOriginalRetrievedAt=original_time,
            sourceRetrievedAt=source_time, providerRetrievedAt=checked_at if refreshed else None)
    if not all(s in output for s in CORE):
        raise ValueError('Fallback did not produce every model input')
    return output, dict(mode='official-provider-fallback', checkedAt=checked_at,
        note='Direct FRED access was incomplete. Identical level series are verified from the official FRED-MD release and Chicago Fed credit CSV. Later cached observations are retained; unsupported series (including USREC labels and optional tenors) keep their original dates. No labels or missing observations are inferred.',
        perSeries=provenance, providerUrls=[FRED_MD_PAGE, CHICAGO_CREDIT_CSV])
