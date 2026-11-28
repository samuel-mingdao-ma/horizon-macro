"""Replay dated counterexamples with a single yield history shared by overlapping issues."""

from math import log, log1p
from forecast_ledger import month_offset


# Keys refer to Treasury observation months. Other observations retain their original
# values in every forecast window. Pairs are [three-month bill bp, ten-year yield bp].
PATHS = {
    'february2019': ('2019-02-01', 3, {'2018-09-01': (-2, -3), '2018-12-01': (2, 3)}),
    'may2000': ('2000-05-01', 5, {'1999-12-01': (-2, -5), '2000-03-01': (2, 5)}),
}


def build_calendar_paths(rows, issues, windows):
    paths = {}
    for name, (date, radius, shifts) in PATHS.items():
        if date not in issues:
            paths[name] = None
            continue
        performance = {}
        summary = {}
        for row in rows:
            origin = row['date']
            shocks = [shifts.get(month_offset(origin, lag), (0, 0)) for lag in (-5, -4, -3, -2)]
            _, point = issues[origin].full_point(shocks)
            performance[origin] = point
        case = performance[date]
        for key, window in windows.items():
            cohort = [r for r in rows if r['commonMature'] and window['windowStart'] <= r['date'] <= window['windowEnd']]
            quiet = [r['date'] for r in cohort if r['target'] == 0]
            err = loss = 0
            for r in cohort:
                p = performance[r['date']]['probability']
                err += (p - r['target'])**2
                clipped = min(max(p, 1e-12), 1 - 1e-12)
                loss -= log(clipped) if r['target'] else log1p(-clipped)
            summary[key] = dict(
                levelQuiet=sum(performance[d]['levelAlert'] for d in quiet),
                alertQuiet=sum(performance[d]['referenceAlert'] for d in quiet),
                brier=err/len(cohort) if cohort else None, logLoss=loss/len(cohort) if cohort else None,
                extraDates=[d for d in quiet if performance[d]['referenceAlert'] and not performance[d]['levelAlert']],
            )
        before = [r for r in rows if r['commonMature'] and r['target'] == 1 and r['onsetDate'] == '2001-04-01']
        first = next((r['date'] for r in before if performance[r['date']]['referenceAlert']), None)
        lead = None if first is None else (2001-int(first[:4]))*12+4-int(first[5:7])
        paths[name] = dict(
            id=name, date=date, radiusBp=radius,
            shocks=[dict(date=d, shortBp=p[0], longBp=p[1]) for d,p in shifts.items()],
            caseRisk=case['probability'], change1m=case['change1m'], change3m=case['change3m'],
            caseLevelAlert=case['levelAlert'], caseAlert=case['referenceAlert'], lead2001=lead,
            extraDates=summary['all']['extraDates'], windows=summary,
        )
    return paths
