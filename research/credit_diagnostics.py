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


def paired_warning_report(trial, labels):
    """Compare two thresholded forecasts on exactly the same mature issues as their probability scores."""
    windows = warning_windows(trial, labels, FORECASTS, {'comparison': ('benchmark', 'candidate')})
    samples = {}
    for name, w in windows.items():
        rows = [
            r
            for r in trial['history']
            if w['windowStart']
            and w['windowEnd']
            and r['commonMature']
            and w['windowStart'] <= r['date'] <= w['windowEnd']
        ]
        samples[name] = rows
        changes = dict(quietRemoved=0, quietAdded=0, preOnsetRemoved=0, preOnsetAdded=0)
        phases = {'expansion-no-recession': 'quiet', 'pre-onset': 'preOnset'}
        for row in rows:
            phase = phases.get(row['issuePhase'])
            candidate_alert = row['probability'] >= THRESHOLD
            if phase and (row['benchmarkProbability'] >= THRESHOLD) != candidate_alert:
                changes[phase + ('Added' if candidate_alert else 'Removed')] += 1
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

    report = dict(
        threshold=THRESHOLD,
        windows=windows,
        gate=both(lambda w: w['comparison']['passes']),
        jointGate=both(lambda w: w['allObjectivesMet']),
    )
    return report, samples


def build_credit_diagnostics(trial, labels):
    report, samples = paired_warning_report(trial, labels)
    report['buckets'] = {}
    for period, rows in samples.items():
        groups = {state: [] for state in STATES}
        for row in rows:
            groups[credit_state(row)].append(row)
        report['buckets'][period] = [summarize_state(state, group) for state, group in groups.items()]
    return report


def build_expansion_diagnostics(trial, labels):
    report, samples = paired_warning_report(trial, labels)
    label_by_month = {month.date().isoformat(): value for month, value in labels.dropna().items()}
    # Phase at the data month is a retrospective diagnostic, never a forecast input or eligibility switch.
    for row in trial['history']:
        value = label_by_month.get(row['featureDate'])
        row['signalMonthRecession'] = int(value) if value is not None else None
    for period, rows in samples.items():
        window = report['windows'][period]
        if window['preOnsetN'] + window['quietExpansionN'] != len(rows):
            raise ValueError('Onset comparisons require retrospectively identified expansion issues')
        dual_expansion = [r for r in rows if r['signalMonthRecession'] == 0]
        window['expansionAtBothDates'] = {
            'n': len(dual_expansion),
            'recessionSignalMonths': sum(r['signalMonthRecession'] == 1 for r in rows),
            'unknownSignalMonths': sum(r['signalMonthRecession'] is None for r in rows),
            **{
                key: fmean((r[field] - r['target']) ** 2 for r in dual_expansion) if dual_expansion else None
                for key, field in FORECASTS.items()
            },
        }
        window['outcomeScores'] = {}
        for name, target in [('quiet', 0), ('preOnset', 1)]:
            group = [r for r in rows if r['target'] == target]
            window['outcomeScores'][name] = {
                'n': len(group),
                **{
                    key: {
                        'meanRisk': fmean(r[field] for r in group) if group else None,
                        'brier': fmean((r[field] - target) ** 2 for r in group) if group else None,
                    }
                    for key, field in FORECASTS.items()
                },
            }
    return report
