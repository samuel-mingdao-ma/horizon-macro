"""Paired alarm changes and calibration of persistent and abrupt credit tightening."""

from statistics import fmean

from weight_warning import THRESHOLD, warning_windows


FORECASTS = {'benchmark': 'benchmarkProbability', 'candidate': 'probability'}
STATES = ('neither', 'persistent', 'sudden', 'both', 'unknown')


def credit_state(row):
    sticky, surprise = row['persistent'], row['sudden']
    if sticky is None or surprise is None:
        return 'unknown'
    if sticky and surprise:
        return 'both'
    return 'persistent' if sticky else 'sudden' if surprise else 'neither'


def summarize_state(state, rows):
    quiet = [r for r in rows if r['issuePhase'] == 'expansion-no-recession']
    positives = sum(int(r['target']) for r in rows)
    return dict(
        state=state,
        n=len(rows),
        positives=positives,
        quietN=len(quiet),
        preOnsetN=sum(r['issuePhase'] == 'pre-onset' for r in rows),
        recessionIssuedPositiveN=sum(
            r['issuePhase'] == 'recession-issued' and r['target'] == 1 for r in rows
        ),
        benchmarkQuietAlerts=sum(r['benchmarkProbability'] >= THRESHOLD for r in quiet),
        candidateQuietAlerts=sum(r['probability'] >= THRESHOLD for r in quiet),
        benchmarkMean=fmean(r['benchmarkProbability'] for r in rows) if rows else None,
        candidateMean=fmean(r['probability'] for r in rows) if rows else None,
        observedRate=positives / len(rows) if rows else None,
    )


def build_credit_diagnostics(trial, labels):
    windows = warning_windows(trial, labels, FORECASTS, {'comparison': ('benchmark', 'candidate')})
    buckets = {}
    for name, w in windows.items():
        rows = [
            r
            for r in trial['history']
            if w['windowStart']
            and w['windowEnd']
            and r['commonMature']
            and w['windowStart'] <= r['date'] <= w['windowEnd']
        ]
        groups = {state: [] for state in STATES}
        changes = dict(quietRemoved=0, quietAdded=0, preOnsetRemoved=0, preOnsetAdded=0)
        for row in rows:
            groups[credit_state(row)].append(row)
            phase = {'expansion-no-recession': 'quiet', 'pre-onset': 'preOnset'}.get(row['issuePhase'])
            candidate_alert = row['probability'] >= THRESHOLD
            if phase and (row['benchmarkProbability'] >= THRESHOLD) != candidate_alert:
                changes[phase + ('Added' if candidate_alert else 'Removed')] += 1
        buckets[name] = [summarize_state(state, groups[state]) for state in STATES]
        w['alertChanges'] = changes
        w['fewerQuietAlarms'] = (
            w['quietExpansionN'] > 0
            and w['summary']['candidate']['quietAlerts'] < w['summary']['benchmark']['quietAlerts']
        )
        w['allObjectivesMet'] = bool(
            trial['gate'][name + 'Passed'] and w['comparison']['passes'] and w['fewerQuietAlarms']
        )

    def both(field):
        return dict(
            allPassed=field(windows['all']),
            rolling120Passed=field(windows['rolling120']),
            passed=all(field(w) for w in windows.values()),
        )

    return dict(
        threshold=THRESHOLD,
        windows=windows,
        buckets=buckets,
        gate=both(lambda w: w['comparison']['passes']),
        jointGate=both(lambda w: w['allObjectivesMet']),
    )
