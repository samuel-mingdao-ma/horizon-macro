"""Compare two pre-specified warning overlays on the same expansion-origin probability."""

from math import isclose

from expansion_trial import COMPLETE_CASE, FEATURES, SPEC as EXPANSION_SPEC
from forecast_ledger import model_probability, month_offset
from leading_trial import number, probability
from weight_warning import THRESHOLD, warning_windows


FLOOR = 0.20
CASE_DATE = '2000-05-01'
CASE_ONSET = '2001-04-01'
ALERTS = {'level': 'levelAlert', 'quarter': 'quarterAlert', 'month': 'monthAlert'}
SPEC = dict(
    id='expansion-onset-warning-pace-v1',
    parentId=EXPANSION_SPEC['id'],
    warningThreshold=THRESHOLD,
    momentumFloor=FLOOR,
    lookbackMonths=3,
    projectionMonths={'quarter': 3, 'month': 1},
    probability='Use the expansion-onset model probability with its original half-weight historical prior.',
    issuedPath='Reprice four consecutive issue-month feature vectors using the current issue’s fit and prior. Each feature date is two months before its source issue.',
    rule='The 30% alarm always fires. Below 30%, require at least 20%, a rising latest month, a positive three-month change, and a continuation of the three-month average pace to 30% within the specified projection horizon.',
    missing='If any path score is missing, use the level rule alone. A missing current probability leaves all decisions unavailable.',
    precision='Compare risks at twelve decimal places. Level and projected threshold comparisons include equality.',
    evaluation='Score all policies on the same mature expansion origins. Require earlier warning in a complete episode, no later complete warnings and zero additional quiet alert-months in both windows. Report strictly earlier mean lead in both separately.',
)


def decisions(path_probs):
    """Compare projections with the threshold in integer units of published precision."""
    if len(path_probs) != 4:
        raise ValueError('Momentum decisions require four consecutive calendar slots')
    if any(p is not None and probability(p) is None for p in path_probs):
        raise ValueError('Momentum path contains an invalid probability')
    unit = 10**12
    start, middle, previous, current = [None if p is None else round(p * unit) for p in path_probs]
    threshold = round(THRESHOLD * unit)
    level = current >= threshold if current is not None else None
    complete = all(p is not None for p in (start, middle, previous, current))
    last_change = current - previous if current is not None and previous is not None else None
    change = current - start if complete else None
    rising = complete and current >= round(FLOOR * unit) and last_change > 0 and change > 0
    return dict(
        change1m=last_change / unit if last_change is not None else None,
        change3m=change / unit if change is not None else None,
        paceAvailable=complete,
        levelAlert=level,
        quarterAlert=(level or (rising and current + change >= threshold)) if level is not None else None,
        monthAlert=(level or (rising and 3 * current + change >= 3 * threshold)) if level is not None else None,
    )


def _issue_path(row, date, features_by_date, model):
    prior = probability(row['expansionPriorProbability'])
    if model is not None and (
        model['featureOrder'] != FEATURES or model['refitDate'] != row['refitDate']
        or model['refitDate'] > date or prior is None
        or not isclose(model['trainingPrevalence'], prior, abs_tol=1e-10, rel_tol=0)
    ):
        raise ValueError('Momentum lookback requires the issue-specific expansion fit and prior')
    result = []
    for lag in range(-3, 1):
        origin = month_offset(date, lag)
        feature_date = month_offset(origin, -2)
        source = features_by_date.get(origin, {}) if lag else row
        if source and source['featureDate'] != feature_date:
            raise ValueError('Momentum features must follow their two-calendar-month release lag')
        features = {name: number(source.get(name)) for name in COMPLETE_CASE}
        risk = None
        if model is not None and all(v is not None for v in features.values()):
            risk = (model_probability(model, features) + prior) / 2
        if lag == 0:
            published = row['probability']
            if published is not None and (risk is None or not isclose(risk, published, abs_tol=1e-8, rel_tol=0)):
                raise ValueError('Current same-fit risk differs from the published expansion forecast')
            risk = published
        result.append(dict(date=origin, featureDate=feature_date, features=features, probability=risk))
    return result


def _read_issue(row, date, features_by_date, model, live=False):
    path = _issue_path(row, date, features_by_date, model)
    risk = [point['probability'] for point in path]
    issue_key = 'issueDate' if live else 'date'
    result = {issue_key: date}
    result.update(
        featureDate=row['featureDate'], refitDate=row['refitDate'], probability=risk[-1],
        lag1Probability=risk[-2], lag2Probability=risk[-3], lag3Probability=risk[-4], **decisions(risk),
    )
    if live:
        result.update(path=path, **{k: row[k] for k in ('forecastStart', 'forecastEnd', 'available', 'reason')})
    else:
        result.update({k: row[k] for k in ('commonMature', 'issuePhase', 'target', 'onsetDate')})
    return result


def _serial_model(model):
    # The live fit returns NumPy arrays; stored coefficients have the same values in ordinary lists.
    return None if model is None else {
        **model, **{k: list(model[k]) for k in ('means', 'scales', 'coefficients')}
    }


def case_comparison(case, paired, episodes):
    # The prior trial identified this episode before the momentum experiment. The same
    # fixed May comparison applies even when it falls outside a window being searched.
    case_leads = any(
        e['onsetDate'] == CASE_ONSET and e['coverage'] == 'full'
        and e['methods']['quarter']['firstAlertDate'] == CASE_DATE
        and (e['methods']['quarter']['leadMonths'] or 0) > (e['methods']['level']['leadMonths'] or 0)
        for e in episodes
    )
    available = bool(
        case and case['commonMature'] and case['target'] == 1 and case['onsetDate'] == CASE_ONSET
        and case['paceAvailable'] and not case['levelAlert'] and case['quarterAlert'] and case_leads
    )
    fields = ('probability', 'change1m', 'change3m')
    matches = []
    if available:
        for row in paired:
            if (row['target'] == 0 and row['paceAvailable'] and not row['levelAlert']
                    and all(round(row[k], 12) >= round(case[k], 12) for k in fields)):
                matches.append({k: row[k] for k in ('date', *fields)})
    return dict(date=CASE_DATE, available=available, matches=matches)


def build_pace_trial(expansion, raw_usrec):
    """Historical issues use their January fit. The live issue uses its separate monthly refit."""
    models = {
        f['refitDate']: _serial_model(f.get('models', {}).get('candidate')) for f in expansion['folds']
    }
    old = expansion['history']
    features = {r['date']: r for r in old}
    if len(features) != len(old):
        raise ValueError('Duplicate month in expansion replay')
    history = [_read_issue(r, r['date'], features, models[r['refitDate']]) for r in old]
    current = expansion['latest']
    live = _read_issue(current, current['issueDate'], features, _serial_model(expansion['currentModel']), live=True)
    windows = warning_windows(
        {'metrics': expansion['metrics'], 'history': history}, raw_usrec, ALERTS,
        {k + 'Comparison': ('level', k) for k in ('quarter', 'month')},
    )
    case = next((r for r in history if r['date'] == CASE_DATE), None)
    for name, window in windows.items():
        paired = [r for r in history if r['commonMature'] and window['windowStart'] <= r['date'] <= window['windowEnd']]
        if window['quietExpansionN'] + window['preOnsetN'] != window['n']:
            raise ValueError('Momentum warning cohort contains a non-expansion or unknown outcome')
        window['caseComparison'] = case_comparison(case, paired, windows['all']['episodes'])
        window['paceAvailableN'] = sum(r['paceAvailable'] for r in paired)
        # All three decisions are overlays on this single probability, so the proper scores coincide.
        window['probabilityScores'] = dict(expansion['metrics'][name]['models']['candidate'])
        window['changes'] = {}
        for key in ('quarter', 'month'):
            added = [r for r in paired if r[ALERTS[key]] and not r['levelAlert']]
            window['changes'][key] = {
                'quietDates': [r['date'] for r in added if r['target'] == 0],
                'preOnsetDates': [r['date'] for r in added if r['target'] == 1],
            }
    gates = {}
    for key in ('quarter', 'month'):
        full, recent = [windows[name][key + 'Comparison'] for name in ('all', 'rolling120')]
        sufficient = full['sufficient'] and recent['sufficient']
        no_false = full['noMoreFalseAlarms'] and recent['noMoreFalseAlarms']
        hits = full['maintainedHits'] and recent['maintainedHits']
        earlier = full['earlier'] > 0 or recent['earlier'] > 0
        gates[key] = dict(
            allNoAddedFalse=full['noMoreFalseAlarms'], rolling120NoAddedFalse=recent['noMoreFalseAlarms'],
            earlierAny=earlier, earlierBoth=full['earlierMean'] and recent['earlierMean'], maintainedHitsBoth=hits,
            passed=sufficient and no_false and hits and earlier and full['later'] == recent['later'] == 0,
        )
    return dict(spec=SPEC, latest=live, history=history, windows=windows, gate=gates)
