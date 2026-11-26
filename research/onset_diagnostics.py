"""Retrospective evaluation by issue phase, onset distance, and expansion calibration.

Outcome labels enter this module only after the walk-forward forecasts have been
made. An onset is the first USREC=1 month after an observed expansion month.
"""

from collections import defaultdict
from math import isfinite
from statistics import fmean

import pandas as pd


FEATURES = ('slope', 'credit', 'labor', 'permitGrowth6', 'claimsGrowth12')
BIN_EDGES = (0, 0.1, 0.2, 0.4, 0.6, 1)
INCUMBENT = 'existingBlendProbability'
CANDIDATE = 'probability'
EPISODE_FIELDS = (
    'date',
    'featureDate',
    'monthsToOnset',
    'originalProbability',
    'baselineProbability',
    INCUMBENT,
    CANDIDATE,
    'permitsBlendProbability',
    'claimsBlendProbability',
    *FEATURES,
)


def _number(value):
    return isinstance(value, (int, float)) and isfinite(value)


def _mean(values):
    observed = [float(value) for value in values if _number(value)]
    return fmean(observed) if observed else None


def _phase(issue, target, labels):
    """Use complete calendar horizons, including the issue month's own label."""
    if not _number(target) or target not in (0, 1):
        return None, None, None
    index = pd.period_range(pd.Period(issue, freq='M'), periods=13, freq='M')
    window = labels.reindex(index)
    if not window.isin([0, 1]).all():
        return None, None, None
    future = window.iloc[1:]
    if int(future.max()) != int(target):
        raise ValueError(f'{issue}: forward USREC labels disagree with the forecast target')
    if window.iloc[0] == 1:
        # Even an issue in the final recession month can have a negative target.
        return 'recession-issued', None, None
    if target == 0:
        return 'expansion-no-recession', None, None
    first = future.index[future.eq(1)][0]
    return 'pre-onset', first.to_timestamp().date().isoformat(), first.ordinal - index[0].ordinal


def _group(rows):
    n = len(rows)
    return dict(
        n=n,
        positiveWindows=sum(int(row['target']) for row in rows),
        observedRate=_mean(row['target'] for row in rows),
        incumbentMean=_mean(row[INCUMBENT] for row in rows),
        candidateMean=_mean(row[CANDIDATE] for row in rows),
        permitsMean=_mean(row.get('permitsBlendProbability') for row in rows),
        rawMean=_mean(row['originalProbability'] for row in rows),
        baseMean=_mean(row['baselineProbability'] for row in rows),
        incumbentBrier=_mean((row['target'] - row[INCUMBENT]) ** 2 for row in rows),
        candidateBrier=_mean((row['target'] - row[CANDIDATE]) ** 2 for row in rows),
        permitsBrier=_mean(
            (row['target'] - row['permitsBlendProbability']) ** 2
            for row in rows
            if _number(row.get('permitsBlendProbability'))
        ),
        blendMinusRaw=_mean(row[INCUMBENT] - row['originalProbability'] for row in rows),
        incumbentBelowRawN=sum(row[INCUMBENT] < row['originalProbability'] for row in rows),
        laborBelowHalfN=sum(_number(row.get('labor')) and round(row['labor'], 10) < 0.50 for row in rows),
        creditNonpositiveN=sum(_number(row.get('credit')) and round(row['credit'], 10) <= 0 for row in rows),
        meanInputs={key: _mean(row.get(key) for row in rows) for key in FEATURES},
    )


def _calibration(expansions, prediction):
    bins = []
    for lower, upper in zip(BIN_EDGES, BIN_EDGES[1:]):
        subset = [
            row
            for row in expansions
            if lower <= row[prediction] < upper or (row[prediction] == 1 and upper == 1)
        ]
        bins.append(dict(lower=lower, upper=upper, **_group(subset)))
    return bins


def _summarize_window(common, metric):
    start, end = metric['windowStart'], metric['windowEnd']
    rows = [row for row in common if start and end and start <= row['date'] <= end]
    if len(rows) != metric['n']:
        raise ValueError('Onset diagnostics must use the same mature issues as the scorecard')
    pre = [row for row in rows if row['issuePhase'] == 'pre-onset']
    quiet = [row for row in rows if row['issuePhase'] == 'expansion-no-recession']
    inside = [row for row in rows if row['issuePhase'] == 'recession-issued']
    expansions = pre + quiet
    groups = {
        'pre1to3': _group([row for row in pre if row['monthsToOnset'] <= 3]),
        'pre4to6': _group([row for row in pre if 4 <= row['monthsToOnset'] <= 6]),
        'pre7to12': _group([row for row in pre if 7 <= row['monthsToOnset']]),
        'preOnset': _group(pre),
        'recessionIssued': _group(inside),
        'quietExpansion': _group(quiet),
        'allExpansion': _group(expansions),
    }
    return dict(
        windowStart=start,
        windowEnd=end,
        n=len(rows),
        unclassifiedN=len(rows) - len(expansions) - len(inside),
        episodeCount=len({row['onsetDate'] for row in pre}),
        groups=groups,
        calibration={
            'incumbent': _calibration(expansions, INCUMBENT),
            'candidate': _calibration(expansions, CANDIDATE),
        },
    )


def build_onset_diagnostics(history, recession_labels, metrics):
    """Annotate monthly CSV rows for evaluation only and return paired diagnostics.

    The parent model supplies its censored target and exact commonMature mask.
    The label series is the original dated USREC vintage truncated at build as-of.
    """
    labels = recession_labels.copy()
    labels.index = pd.DatetimeIndex(labels.index).to_period('M')
    if labels.index.has_duplicates:
        raise ValueError('Duplicate calendar months in USREC')
    common = []
    episodes = defaultdict(list)
    for row in history:
        issue = row['date']
        phase, onset, lead = _phase(issue, row.get('target'), labels)
        row.update(issuePhase=phase, onsetDate=onset, monthsToOnset=lead)
        if not row['commonMature']:
            continue
        common.append(row)
        if onset:
            episodes[onset].append({key: row.get(key) for key in EPISODE_FIELDS})

    return dict(
        windows={key: _summarize_window(common, metrics[key]) for key in ('all', 'rolling120')},
        episodes=[
            dict(onsetDate=start, rows=sorted(rows, key=lambda row: row['date']))
            for start, rows in sorted(episodes.items())
        ],
        calibrationEdges=list(BIN_EDGES),
        notes=[
            'Onset is the first monthly USREC value of one following a zero. With this convention the 2020 onset is March, after the February NBER peak.',
            'A row is classified only if the official outcome and all thirteen monthly USREC labels from the issue month through the horizon end are present.',
            'Lead distances and phase assignments use hindsight only for evaluation. Each forecast uses its dated inputs.',
            'Calibration includes all scored expansion-issued months with classified outcomes. Each model uses its own probability bins, with 100% included in the final bin.',
            'Conditioning on a future recession selects positive windows. The observed event rate in such windows is one by construction.',
            'Adjacent twelve-month horizons overlap. Episode paths count only observed issues, and a single recession can contribute multiple positives.',
        ],
    )
