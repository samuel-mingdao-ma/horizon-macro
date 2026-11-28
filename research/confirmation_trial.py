"""Housing, employment and credit confirmation of the pre-specified three-month pace alarm."""

from math import exp, expm1, fsum, isclose

from expansion_trial import FEATURES, SPEC as EXPANSION_SPEC
from forecast_ledger import month_offset
from leading_trial import number
from pace_trial import CASE_DATE, CASE_ONSET, SPEC as PACE_SPEC
from weight_warning import warning_windows


CASE_DATES = (CASE_DATE, '2019-02-01')
RULES = ('pressure', 'direction', 'breadth')
ALERTS = {method: method + 'Alert' for method in ('level', 'quarter', *RULES)}
SIGNALS = ('permitGrowth6', 'claimsGrowth12', 'credit')
OUTCOME_FIELDS = ('commonMature', 'issuePhase', 'target', 'onsetDate')
SPEC = dict(
    id='expansion-onset-cross-signal-confirmation-v1',
    parentId=PACE_SPEC['id'],
    threshold=PACE_SPEC['warningThreshold'],
    featureLagMonths=2,
    signalLookbackMonths=3,
    scope='Keep each level alarm and each published conditional probability. Test confirmation only on extra three-month pace alarms.',
    pressure='Require negative six-month permit growth, positive twelve-month initial-claims growth, and a credit index higher than three months earlier.',
    direction='Require permit growth below its value three months earlier, claims growth above its value three months earlier, and a higher credit index.',
    breadth='Require at least two of the three pressure votes. All three votes must be observed.',
    precision='Round each input to twelve decimal places before strict sign and direction comparisons. Equality gives no confirmation.',
    clock='Each input belongs to the observation month two calendar months before its forecast issue. Use the exact third prior month for changes.',
    missing='Missing required votes disable the extra alert for that rule. A missing probability leaves all decisions unavailable.',
    test='Keep the May 2000 alert and at least eleven months of lead before April 2001, exceed the level rule’s lead, preserve complete detections, and add zero quiet alerts in both windows.',
)


def signal_evidence(current, lagged):
    """A missing field affects only the votes depending on it."""
    def readings(vector):
        values = (number((vector or {}).get(key)) for key in SIGNALS)
        return [round(x, 12) if x is not None else None for x in values]

    permits, claims, credit = readings(current)
    prior_permits, prior_claims, prior_credit = readings(lagged)
    permits_negative = permits < 0 if permits is not None else None
    claims_positive = claims > 0 if claims is not None else None
    tightening = credit > prior_credit if None not in (credit, prior_credit) else None
    permits_slowing = permits < prior_permits if None not in (permits, prior_permits) else None
    claims_rising = claims > prior_claims if None not in (claims, prior_claims) else None
    pressure = (permits_negative, claims_positive, tightening)
    direction = (permits_slowing, claims_rising, tightening)
    return dict(
        permitGrowth6=permits, claimsGrowth12=claims, credit=credit,
        lagPermitGrowth6=prior_permits, lagClaimsGrowth12=prior_claims, lagCredit=prior_credit,
        permitsNegative=permits_negative, claimsPositive=claims_positive, creditTightening=tightening,
        permitsSlowing=permits_slowing, claimsRising=claims_rising,
        pressureVotes=sum(pressure) if None not in pressure else None,
        directionVotes=sum(direction) if None not in direction else None,
    )


def confirmation_decisions(level, quarter, pressure_votes, direction_votes):
    if not ((level is None and quarter is None)
            or (type(level) is bool and type(quarter) is bool and (not level or quarter))):
        raise ValueError('Inconsistent baseline and parent pace decisions')
    if any(v is not None and (type(v) is not int or not 0 <= v <= 3) for v in (pressure_votes, direction_votes)):
        raise ValueError('Confirmation requires a complete vote count from zero to three')
    if level is None:
        return {ALERTS[k]: None for k in RULES}
    return dict(
        pressureAlert=level or (quarter and pressure_votes == 3),
        directionAlert=level or (quarter and direction_votes == 3),
        breadthAlert=level or (quarter and pressure_votes is not None and pressure_votes >= 2),
    )


def issue_record(origin, pace, expansion_history, *, live=False):
    key = 'issueDate' if live else 'date'
    date = pace[key]
    lag = month_offset(date, -3)
    lagged = expansion_history.get(lag)
    lag_feature_date = month_offset(lag, -2)
    if (origin[key] != date or origin['featureDate'] != month_offset(date, -2)
            or pace['featureDate'] != origin['featureDate'] or pace['refitDate'] != origin['refitDate']
            or (lagged is not None and lagged['featureDate'] != lag_feature_date)):
        raise ValueError('Confirmation requires aligned monthly issues and two-month-lagged inputs')
    if (pace['probability'] != origin['probability']
            or (pace['probability'] is None) != (pace['levelAlert'] is None)):
        raise ValueError('Confirmation and expansion probability must share the same issue')
    evidence = signal_evidence(origin, lagged)
    result = {
        key: date, 'featureDate': origin['featureDate'], 'lagFeatureDate': lag_feature_date,
        **{k: pace[k] for k in ('refitDate', 'probability', 'change1m', 'change3m', 'levelAlert', 'quarterAlert')},
        **evidence, **confirmation_decisions(
            pace['levelAlert'], pace['quarterAlert'], evidence['pressureVotes'], evidence['directionVotes']
        ),
    }
    extras = ('forecastStart', 'forecastEnd', 'available', 'reason') if live else OUTCOME_FIELDS
    if any(origin[k] != pace[k] for k in extras):
        raise ValueError('Confirmation requires the same expansion forecast clock and outcome cohort')
    result.update({k: pace[k] for k in extras})
    return result


def evaluation_gates(windows, may):
    event = next((e for e in windows['all']['episodes'] if e['onsetDate'] == CASE_ONSET and e['coverage'] == 'full'), None)
    comparable = bool(
        event and may and may['commonMature'] and may['target'] == 1 and may['onsetDate'] == CASE_ONSET
        and not may['levelAlert'] and may['quarterAlert']
    )
    gates = {}
    for key in RULES:
        full, recent = (windows[w][key + 'Comparison'] for w in ('all', 'rolling120'))
        lead = (event['methods'][key]['leadMonths'] or 0) if event else 0
        retained = bool(comparable and may[ALERTS[key]] and lead >= 11 and lead > (event['methods']['level']['leadMonths'] or 0))
        hits = full['maintainedHits'] and recent['maintainedHits']
        gates[key] = dict(
            mayRetained=retained, allNoAddedFalse=full['noMoreFalseAlarms'],
            rolling120NoAddedFalse=recent['noMoreFalseAlarms'], maintainedHitsBoth=hits,
            passed=bool(retained and hits and full['sufficient'] and recent['sufficient']
                        and full['noMoreFalseAlarms'] and recent['noMoreFalseAlarms']),
        )
    return gates


def _logistic(z):
    return 1 / (1 + exp(-z)) if z >= 0 else exp(z) / (1 + exp(z))


def case_attribution(start, end, pace, model):
    """Integrate each fitted input's marginal effect along a straight path between endpoints."""
    if (not start or not end or not model or not pace or not pace['paceAvailable']
            or any(number(r.get(k)) is None for r in (start, end) for k in FEATURES)):
        return None
    if (model['refitDate'] != end['refitDate'] or model['featureOrder'] != FEATURES
            or any(scale <= 0 for scale in model['scales'])):
        raise ValueError('Case attribution requires the issue-specific expansion fit')
    coefficients = [float(b / scale) for b, scale in zip(model['coefficients'], model['scales'])]
    logit_start = model['intercept'] + fsum((start[k] - m) * b for k, m, b in zip(FEATURES, model['means'], coefficients))
    shifts = {k: (end[k] - start[k]) * b for k, b in zip(FEATURES, coefficients)}
    distance = fsum(shifts.values())
    low, high = sorted((logit_start, logit_start + distance))
    # Divided difference of the sigmoid, with the derivative as its continuous zero-distance limit.
    factor = -expm1(-abs(distance)) / abs(distance) if distance != 0 else 1.0
    mean_gradient = _logistic(high) * _logistic(-low) * factor
    weight = EXPANSION_SPEC['modelWeight']
    effects = {k: weight * mean_gradient * shift for k, shift in shifts.items()}
    prior_part = (1 - weight) * model['trainingPrevalence']
    start_risk = prior_part + weight * _logistic(logit_start)
    end_risk = prior_part + weight * _logistic(logit_start + distance)
    if not all(isclose(a, b, abs_tol=1e-8, rel_tol=0) for a, b in (
        (start_risk, pace['lag3Probability']), (end_risk, pace['probability']), (fsum(effects.values()), pace['change3m'])
    )):
        raise ValueError('Case attribution must reproduce the three-month same-fit probability path')
    return dict(startRisk=pace['lag3Probability'], endRisk=pace['probability'], change=pace['change3m'], effects=effects)


def build_confirmation_trial(expansion, momentum, raw_usrec):
    origins = {r['date']: r for r in expansion['history']}
    dates = [r['date'] for r in momentum['history']]
    if len(origins) != len(expansion['history']) or dates != list(origins) or dates != sorted(dates):
        raise ValueError('Confirmation requires the same ordered expansion and momentum issue months')
    history = [issue_record(origins[r['date']], r, origins) for r in momentum['history']]
    latest = issue_record(expansion['latest'], momentum['latest'], origins, live=True)
    windows = warning_windows(
        {'metrics': expansion['metrics'], 'history': history}, raw_usrec, ALERTS,
        {k + 'Comparison': ('level', k) for k in RULES},
    )
    for label, w in windows.items():
        paired = [r for r in history if r['commonMature'] and w['windowStart'] <= r['date'] <= w['windowEnd']]
        if w['quietExpansionN'] + w['preOnsetN'] != w['n']:
            raise ValueError('Confirmation evaluation requires exclusively mature expansion-origin months')
        w['probabilityScores'] = dict(expansion['metrics'][label]['models']['candidate'])
        w['changes'] = {}
        for key in ('quarter', *RULES):
            added = [r for r in paired if r[ALERTS[key]] and not r['levelAlert']]
            w['changes'][key] = dict(
                quietDates=[r['date'] for r in added if r['target'] == 0],
                preOnsetDates=[r['date'] for r in added if r['target'] == 1],
            )
    may = next((r for r in history if r['date'] == CASE_DATE), None)
    paces = {r['date']: r for r in momentum['history']}
    models = {f['refitDate']: f.get('models', {}).get('candidate') for f in expansion['folds']}
    attribution = {}
    for date in CASE_DATES:
        origin = origins.get(date)
        attribution[date] = case_attribution(
            origins.get(month_offset(date, -3)), origin, paces.get(date), models.get(origin['refitDate']) if origin else None
        )
    return dict(spec=SPEC, latest=latest, history=history, windows=windows,
                gate=evaluation_gates(windows, may), caseAttribution=attribution)
