# HORIZON research note

HORIZON estimates the probability that **at least one of the next twelve calendar months is classified as a U.S. recession month**. This includes continuation of an existing recession. It is not an onset-only probability, a forecast of GDP growth, or a financial return forecast.

The headline is an experimental model estimate. Historical probability calibration is imperfect: the model ranks risk better than the curve-only comparator, but its Brier score and log loss are worse than the expanding historical base-rate comparator. Readers should not mistake discrimination for well-calibrated probabilities.

## Data and attribution

The pipeline first requests original series from FRED's chart CSV endpoint (or its official API when an optional `FRED_API_KEY` is configured). Cloud downloads can time out. In that case, it verifies identical level series using the official FRED-MD monthly release and the Chicago Fed's current credit CSV. FRED-MD transformation codes are not applied. Required alternative-provider access must succeed; an unavailable feed fails the build rather than fabricating observations.

`research/raw/` holds normalized cached series used by the model. Original alternative-provider responses and retrieval provenance are retained in `research/provider-cache/`. Series unsupported by the alternative feeds, including USREC and optional Treasury tenors, retain their dated cache. Missing future recession labels remain unknown: feature months can advance without extending the evaluation cutoff. The full Treasury curve uses the latest month shared by every displayed tenor.

`meta.dataRefresh` and source-level fields identify provider URLs, actual retrieval timestamps, verified provider cutoff, retained later cached observations, label cutoff, and common curve month. A new research-build timestamp does not imply every series received a new observation.

- **GS10**: Board of Governors of the Federal Reserve System, monthly 10-year constant maturity Treasury yield, investment basis. [Source](https://fred.stlouisfed.org/series/GS10)
- **TB3MS**: Board of Governors of the Federal Reserve System, monthly 3-month Treasury bill secondary market rate, discount basis. [Source](https://fred.stlouisfed.org/series/TB3MS)
- **NFCICREDIT**: Federal Reserve Bank of Chicago, weekly National Financial Conditions Index credit subindex; retrieved from FRED, Federal Reserve Bank of St. Louis. [Source](https://fred.stlouisfed.org/series/NFCICREDIT)
- **UNRATE**: U.S. Bureau of Labor Statistics, monthly seasonally adjusted unemployment rate. [Source](https://fred.stlouisfed.org/series/UNRATE)
- **USREC**: Federal Reserve Bank of St. Louis, NBER-based recession indicators from the period following the peak through the trough; retrieved from FRED, Federal Reserve Bank of St. Louis. [Source](https://fred.stlouisfed.org/series/USREC)
- **CPIAUCSL**: U.S. Bureau of Labor Statistics, seasonally adjusted CPI; used for context, excluded from prediction features. [Source](https://fred.stlouisfed.org/series/CPIAUCSL)
- **FEDFUNDS** and **GS1/GS2/GS5/GS30**: Board of Governors of the Federal Reserve System; used for context and the yield-curve display, excluded from prediction features. [Source](https://fred.stlouisfed.org/series/FEDFUNDS)

The Chicago Fed credit subindex is a conditions index, **not a traded credit spread**. Positive readings indicate tighter than average conditions. Its historical factor estimates and full-sample normalization can be revised. GS10 minus TB3MS is this project's yield-curve proxy; because the underlying quote bases differ, it is not an exact New York Fed model replication or a common-basis Treasury spread.

## Feature construction

The calendar-month panel begins in March 1971, after allowing two months for the lag on NFCICREDIT's January 1971 start. Missing calendar months are never compressed out of time.

At forecast issue month `t`, every predictive input is drawn from observation month `t−2`:

1. **Curve slope**: GS10 minus TB3MS, in percentage points.
2. **Credit conditions**: arithmetic mean of weekly NFCICREDIT readings whose observation dates fall within that complete calendar month. There is no partial-current-month aggregation.
3. **Labor gap**: three-calendar-month moving mean of UNRATE minus the minimum of twelve consecutive such smoothed values, including the current one. A three-month mean requires at least two observed monthly rates. All twelve smoothed values are required for the minimum.

The available-observation labor policy is explicit because the official October 2025 unemployment observation is blank. No unemployment observation is interpolated or invented. October, November and December 2025 smoothing windows therefore use the two available observations in each three-calendar-month window. The policy is applied consistently to the full historical panel.

CPI year-over-year inflation is `100 × (CPI_t/CPI_(t−12) − 1)`. If the year-ago observation is missing, that month's inflation is missing. The website shows the most recent computable year-over-year value with its own observation date; this can differ from the current Treasury or unemployment observation month.

## Target and forecast clock

`target_t = max(USREC_(t+1), ..., USREC_(t+12))`.

All twelve future monthly observations must be present to score a forecast. Recent target values remain unavailable. For example, a November 2026 forecast uses September 2026 features and covers December 2026 through November 2027.

Historical predictions are generated by an annual expanding-window walk-forward exercise beginning January 1990. For the January refit in each year:

- Eligible training issue months end at or before `refit_month − 13 months`.
- Therefore the latest training target month is strictly earlier than the refit month.
- The model, standardization and historical base rate are estimated on that training set only.
- The fitted model is held fixed for all twelve forecast issue months in the next calendar year.
- No random shuffle or random train/test split is used.

For example, the January 1990 refit trains on issue dates through December 1988; its last training target ends December 1989. This prevents overlapping target windows across the training/test boundary.

The current production estimate is separately refitted each issue month on all mature eligible targets. The historical chart explicitly tags its last point as a current-month refit. Historical downloadable predictions retain the annual walk-forward estimates. The reported month-over-month headline change scores both months' features using the same current production model, so it measures changing inputs rather than model-refit drift.

## Estimation

The model is logistic regression with three features, an unpenalized intercept and a fixed L2 penalty of 1 on standardized feature coefficients:

`min Σ[log(1 + exp(z_i)) − y_i z_i] + 0.5 Σ β_j²`.

Each feature is centered and scaled using training-sample mean and population standard deviation only. The penalty applies to the **summed** likelihood, not its average. There is no class weighting, cross-validated parameter search or retrospective threshold optimization. Newton iterations with a numerical line search solve the convex objective. Production JSON includes means, scales, standardized coefficients and mathematically equivalent raw coefficients for independent scoring.

The curve-only comparator uses the same target, observation lag, training dates, standardization and L2 procedure with only the slope feature. The base-rate comparator is the expanding training target proportion. It is estimated independently at every refit; it is not the full-period realized prevalence.

For display only, fixed descriptive score bands are: below 15% Contained; 15% to below 30% Watchful; 30% and above Elevated. They have no special economic or optimized classification meaning.

## Validation and current results

The current saved research run scores 430 mature monthly forecast issues from January 1990 through October 2025. These contain 75 positive twelve-month target windows, 36 actual recession months and only **four distinct recession episodes**.

| Metric | Three-signal model | Curve only | Expanding base rate |
|---|---:|---:|---:|
| ROC AUC; higher is better | 0.7822 | 0.7097 | 0.3617 |
| Brier score; lower is better | 0.17045 | 0.17943 | 0.16057 |
| Log loss; lower is better | 0.56967 | 0.55086 | 0.50590 |

The result is mixed. Additional signals improve risk ranking and Brier score relative to the curve-only model, but **do not beat the simple base rate on probability error**. A high AUC should never be presented as 78% accuracy. The base-rate comparator changes slowly across annual refits, so its AUC measures the accidental ordering of those historical levels, not a useful timing signal.

A central failure case is July 2023: the model estimated 96.675% for at least one recession month during August 2023–July 2024, while the currently published target is zero. Strongly inverted curves in 2023–2024 produced persistent overconfidence without a subsequent NBER recession. This is evidence of calibration and regime limitations, not something removed from the sample.

A stricter label-availability sensitivity allows training issue dates only through `refit − 25 months`, placing the last target month at least twelve months before the refit. It produces AUC 0.7814 and Brier 0.17370. This additional delay does not eliminate the revised-history limitation.

**Exploratory calibration hypothesis, not a validated replacement.** After examining the historical model's overconfidence, a 50/50 average of each annual walk-forward model probability and that same fold's expanding training base rate was calculated on the same 430 evaluation months. It yields AUC 0.7665, Brier 0.14047 and log loss 0.44630. This improves historical probability error while reducing discrimination, illustrating the potential value of shrinkage. However, the diagnostic was designed after looking at this test sample: it is post-hoc exploration, not untouched holdout evidence, an independently selected winner, or proof that the blend will improve future forecasts. The production model and headline are unchanged. The hypothesis requires future-vintage or genuinely untouched-period evaluation before promotion. Its metrics are stored as `metrics.exploratoryBlend`, with annual diagnostic values in the download's `blendProbability` column.

No conventional independent-observation confidence interval is reported. Monthly twelve-month targets overlap heavily, and only four test recessions provide limited independent evidence. A proper uncertainty analysis would resample long time blocks or whole business-cycle episodes and report sensitivity to block definitions.

## Interpreting signals and stress scenarios

The contribution display decomposes the current model's **log odds**, not probability percentage points. Each feature contribution is `β_j × standardized_feature_j`; adding the intercept and applying the logistic function reconstructs the forecast exactly. A feature may increase risk relative to the training mean even if its raw level looks benign.

The fitted labor coefficient is close to zero and slightly negative conditional on the curve and credit inputs. HORIZON does not claim that worse unemployment mechanically lowers real economic risk; this coefficient reflects the chosen long-horizon target, correlated features and the limited historical sample. Univariate economic narratives must not be substituted for fitted model behavior.

Interactive stress scenarios hold the trained coefficients fixed while changing inputs. Their output is a **conditional model sensitivity**, not a causal counterfactual, a priced market forecast, or a probability attached to the scenario itself. Duration and convexity calculations describe local bond-price sensitivity to an assumed parallel yield shift; they are separate from the macro probability model.

## What this research does not establish

This is a **latest-vintage historical simulation**, not a historical real-time vintage backtest. Current UNRATE and NFCI data incorporate revisions unavailable at the historical issue date. The Chicago Fed index may itself be reestimated using later information even though HORIZON's own standardization uses only its training window.

NBER dates are announced retrospectively. A target containing twelve currently available zero observations is not guaranteed to be settled historical truth. The calendar purge removes target-window overlap, but it does not reconstruct actual historical announcement availability. The stricter delayed-label sensitivity only partially addresses this concern.

The model excludes equity valuations, fiscal policy, sector-specific lending and structural changes. It can miss sudden shocks and can assign high probabilities to recessions that never happen. A hiring discussion should focus on these diagnostics and the reproducible research design, rather than claiming a reliable trading edge.

## Reproduce and audit

```sh
python3 -m pip install numpy pandas requests
python3 research/build_model.py --refresh
python3 research/test_model.py
```

To reproduce the saved data without a fresh download:

```sh
python3 research/build_model.py --offline --as-of 2026-11-25
```

Outputs: canonical `data/snapshot.json`; browser fallback `public/data/snapshot.json`; downloadable `public/data/panel.csv` and `public/data/predictions.csv`; full fold eligibility audit in `research/folds.json`. The test suite checks target alignment, unavailable future labels, two-month feature timing, disjoint train/test target boundaries, training-only scaling, raw/standardized/contribution parity, independent metric recomputation, monthly credit aggregation, the optimizer's penalized gradient, and missing unemployment handling.
