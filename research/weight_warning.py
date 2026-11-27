"""Retrospective episode timing and false alarms for the predeclared 30% warning rule."""

from math import isfinite
from statistics import fmean

import pandas as pd


THRESHOLD = 0.30
FORECASTS = {
    'existingBlend': 'existingBlendProbability',
    'fixedPermits': 'fixedPermitsProbability',
    'candidate': 'probability',
    'fixedRule': 'fixedRuleProbability',
    'originalDynamic': 'originalDynamicProbability',
}


def _month(date):
    return pd.Period(date, freq='M')


def _date(month):
    return month.to_timestamp().date().isoformat() if month is not None else None


def _lead(onset, issue):
    return onset.ordinal - issue.ordinal if issue is not None else None


def _score(value):
    return isinstance(value, (int, float)) and isfinite(value) and 0 <= value <= 1


def _ratio(count, total):
    return count / total if total else None


def _onsets(raw):
    labels = raw.copy()
    labels.index = pd.DatetimeIndex(labels.index).to_period('M')
    if labels.index.has_duplicates or not labels.dropna().isin([0, 1]).all():
        raise ValueError('Expected unique monthly USREC observations with binary values')
    if labels.empty:
        return []
    labels = labels.reindex(pd.period_range(labels.index.min(), labels.index.max(), freq='M'))
    return labels.index[(labels == 1) & (labels.shift(1) == 0)].tolist()


def _episode_model(onset, dates, history, field):
    flagged = [date for date in dates if history[date][field] >= THRESHOLD]
    first = flagged[0] if flagged else None
    kinds = {}
    for date in flagged:
        previous = history.get(date - 1, {}).get(field)
        kinds[date] = (
            'previous-unknown'
            if not _score(previous)
            else 'already-high' if previous >= THRESHOLD else 'new-crossing'
        )
    crossing = next((date for date in flagged if kinds[date] == 'new-crossing'), None)
    # A missing predecessor for an earlier alarm can hide the first true crossing.
    unknown = any(
        kind == 'previous-unknown' and (crossing is None or date < crossing) for date, kind in kinds.items()
    )
    return dict(
        firstAlertDate=_date(first),
        leadMonths=_lead(onset, first),
        firstAlertKind=kinds.get(first),
        flaggedMonths=len(flagged),
        firstCrossDate=_date(crossing),
        crossLeadMonths=_lead(onset, crossing),
        firstCrossUncertain=unknown,
    )


def _episode(onset, start, end, paired, history):
    calendar = pd.period_range(onset - 12, onset - 1, freq='M')
    within = [date for date in calendar if start <= date <= end]
    if not within:
        return None
    observed = [date for date in within if date in paired]
    onset_date = _date(onset)
    eligible = [
        date
        for date in observed
        if paired[date]['issuePhase'] == 'pre-onset' and paired[date]['onsetDate'] == onset_date
    ]
    return dict(
        onsetDate=onset_date,
        expectedMonths=12,
        availableMonths=len(eligible),
        coverage='full' if len(eligible) == 12 else 'partial' if eligible else 'unavailable',
        outsideWindowMonths=12 - len(within),
        missingPairedMonths=len(within) - len(observed),
        otherOrUnknownPhaseMonths=len(observed) - len(eligible),
        methods={key: _episode_model(onset, eligible, history, field) for key, field in FORECASTS.items()},
    )


def _summarize_method(key, episodes, phase_rows):
    field = FORECASTS[key]
    methods = [episode['methods'][key] for episode in episodes]
    leads = [episode['leadMonths'] or 0 for episode in methods]
    cross_leads = [episode['crossLeadMonths'] or 0 for episode in methods]
    quiet, pre, inside = (
        phase_rows[phase] for phase in ['expansion-no-recession', 'pre-onset', 'recession-issued']
    )
    quiet_alerts = sum(row[field] >= THRESHOLD for row in quiet)
    pre_alerts = sum(row[field] >= THRESHOLD for row in pre)
    return dict(
        completeHits=sum(lead > 0 for lead in leads),
        meanLeadMonths=fmean(leads) if leads else None,
        ceilingEpisodes=leads.count(12),
        completeCrossHits=sum(lead > 0 for lead in cross_leads),
        meanCrossLeadMonths=(
            fmean(cross_leads) if methods and not any(m['firstCrossUncertain'] for m in methods) else None
        ),
        uncertainCrossEpisodes=sum(m['firstCrossUncertain'] for m in methods),
        quietAlerts=quiet_alerts,
        quietRate=_ratio(quiet_alerts, len(quiet)),
        preOnsetAlerts=pre_alerts,
        preOnsetRate=_ratio(pre_alerts, len(pre)),
        recessionIssuedAlerts=sum(row[field] >= THRESHOLD for row in inside),
    )


def _compare(episodes, summary, reference, contender='candidate'):
    candidate, baseline = summary[contender], summary[reference]
    differences = [
        (episode['methods'][contender]['leadMonths'] or 0)
        - (episode['methods'][reference]['leadMonths'] or 0)
        for episode in episodes
    ]
    earlier = sum(delta > 0 for delta in differences)
    later = sum(delta < 0 for delta in differences)
    # Both methods share exactly the same quiet-expansion and episode denominators.
    earlier_mean = bool(episodes and sum(differences) > 0)
    maintained_hits = bool(episodes and candidate['completeHits'] >= baseline['completeHits'])
    no_more_false = candidate['quietRate'] is not None and candidate['quietAlerts'] <= baseline['quietAlerts']
    return dict(
        earlier=earlier,
        tied=len(differences) - earlier - later,
        later=later,
        earlierMean=earlier_mean,
        maintainedHits=maintained_hits,
        noMoreFalseAlarms=no_more_false,
        sufficient=bool(episodes and candidate['quietRate'] is not None),
        baselineAtCeiling=bool(episodes and baseline['ceilingEpisodes'] == len(episodes)),
        passes=earlier_mean and maintained_hits and no_more_false,
    )


def _window(metric, onsets, history):
    first, last = metric['windowStart'], metric['windowEnd']
    start, end = _month(first) if first else None, _month(last) if last else None
    paired = {
        date: row
        for date, row in history.items()
        if start is not None and end is not None and start <= date <= end and row['commonMature']
    }
    if len(paired) != metric['n'] or any(
        not all(_score(row.get(field)) for field in FORECASTS.values()) for row in paired.values()
    ):
        raise ValueError(
            'Warning evaluation requires the same paired mature predictions as the Brier comparison'
        )
    episodes = []
    for onset in onsets:
        if start is None or end is None or not start < onset <= end + 12:
            continue
        episodes.append(_episode(onset, start, end, paired, history))
    complete = [episode for episode in episodes if episode['coverage'] == 'full']
    phase_rows = {
        phase: [row for row in paired.values() if row['issuePhase'] == phase]
        for phase in ['expansion-no-recession', 'pre-onset', 'recession-issued']
    }
    if any(row['target'] != 0 for row in phase_rows['expansion-no-recession']) or any(
        row['target'] != 1 for row in phase_rows['pre-onset']
    ):
        raise ValueError('Pre-onset and quiet-expansion phases disagree with their twelve-month targets')
    summary = {key: _summarize_method(key, complete, phase_rows) for key in FORECASTS}
    return dict(
        windowStart=first,
        windowEnd=last,
        n=len(paired),
        quietExpansionN=len(phase_rows['expansion-no-recession']),
        preOnsetN=len(phase_rows['pre-onset']),
        recessionIssuedN=len(phase_rows['recession-issued']),
        unclassifiedN=len(paired) - sum(len(group) for group in phase_rows.values()),
        completeEpisodes=len(complete),
        partialEpisodes=sum(row['coverage'] == 'partial' for row in episodes),
        unavailableEpisodes=sum(row['coverage'] == 'unavailable' for row in episodes),
        episodes=episodes,
        summary=summary,
        comparison=_compare(complete, summary, 'existingBlend'),
        versusFixedPermits=_compare(complete, summary, 'fixedPermits'),
        fixedRuleComparison=_compare(complete, summary, 'existingBlend', contender='fixedRule'),
    )


def build_weight_warnings(trial, raw_usrec):
    """Enumerate observed USREC 0→1 onsets independently of the candidate's coverage."""
    history = {_month(row['date']): row for row in trial['history']}
    if len(history) != len(trial['history']):
        raise ValueError('Duplicate monthly issue in the weight-trial replay')
    onsets = _onsets(raw_usrec)
    windows = {key: _window(trial['metrics'][key], onsets, history) for key in ['all', 'rolling120']}

    def gate(comparison):
        full = windows['all'][comparison]['passes']
        recent = windows['rolling120'][comparison]['passes']
        return dict(allPassed=full, rolling120Passed=recent, passed=full and recent)

    return dict(
        threshold=THRESHOLD,
        windows=windows,
        gate=gate('comparison'),
        ruleGate=gate('fixedRuleComparison'),
        notes=[
            'The site’s fixed 30% threshold applies to every forecast. An alert includes equality.',
            'First alert lead is measured from the earliest flagged expansion issue in the twelve months before onset. A previously elevated alert can qualify.',
            'A new crossing requires an observed below-threshold forecast one calendar month earlier. A previous forecast outside the score window is used only to identify crossings.',
            'Mean lead uses all complete twelve-month episodes. A missed episode contributes zero. Partial or unavailable episodes remain visible and are excluded from this mean.',
            'Quiet false-alarm rate is the fraction of paired expansion issues with no recession in the next twelve months that nevertheless raised an alert.',
            'The timing test requires a longer mean lead, at least as many detected complete episodes and no higher quiet false-alarm rate, in both evaluation windows.',
        ],
    )
