# Alarm Lab: a testable improvement that did not cure the failure

Initial publication, **November 2026 forecast issue**. Exact research-build and receipt-capture timestamps are recorded in the downloadable artifacts. The original model's 2023 false alarm motivates a specific question: **Does credit or labor confirmation improve a yield-curve warning, and what does waiting for confirmation cost?** The project contribution is an inspectable workflow—conditional modelling, failure replay, decision costs, and frozen future forecasts. It does not claim a new statistical method or an established trading advantage.

## Decision brief: state a view and define what would change it

The [Decision brief](https://horizon-macro-observatory.samel23.chatgpt.site/#brief) connects the current signal reading to explicit monitoring conditions. Its reverse-trigger tool fixes the curve and labor inputs, chooses an illustrative alarm level, and solves the fitted model for the required credit value. This makes a conditional view inspectable without claiming that the model is well calibrated.

For raw coefficients, let curve slope be `s`, labor gap `l`, credit index `c`, intercept `b`, and coefficients `a_s`, `a_l`, `a_c`, `a_i`. At fixed `s` and `l`:

```text
k(s) = a_c + a_i × max(−s, 0)
c* = [log(p*/(1−p*)) − b − a_s×s − a_l×l] / k(s)
```

For the original model, `a_i = 0`. If `k(s) > 0`, crossing the probability alarm requires credit at or above `c*`; if negative, the inequality reverses. If the credit effect is zero, changing credit cannot produce a unique finite crossing. Solvers verify parameter consistency and recompute the interaction when inputs change.

At the initial inputs of slope **1.05 pp**, labor gap **0.00 pp**, and credit **−0.03475**, a **30%** threshold gives original `c* = 0.38550`, a **+0.42025 index** shift; the candidate gives `0.36063`, a **+0.39538 index** shift. These units are index units, not basis points. They are **model crossings, not causal tipping points, confidence intervals, or probabilities that credit will reach that value**. Input-support counts use only the curve–credit plane and ignore labor distance.

Three triggers remain distinct: credit above zero or labor gap at least 0.50 pp activates the exploratory confirmation rule; the reverse solver crosses a selected fitted probability; and a mature future outcome changes the prospective score. One does not establish the others.

The [downloadable HTML memo](https://horizon-macro-observatory.samel23.chatgpt.site/api/brief), served by `GET /api/brief`, records the retrieved snapshot's dates, current view, caveats, and separate rate exposure. It can be read or printed independently of the website. It is a dated current memo, not a frozen ledger receipt or a record of every client-side slider choice.

### Course concepts: recession exposure and duration exposure are separate

The memo applies cash-flow discounting to an illustrative **$1m, ten-year, semiannual coupon bond**, with its fixed coupon set at the baseline ten-year yield. Exact instantaneous repricing under ±100 bp parallel yield shifts shows rate sensitivity. The scenario lab also compares duration/convexity approximations and DV01.

The macro model does not determine a future yield move, and its credit-conditions index is not a traded bond spread. The bond examples hold cash flows fixed and exclude elapsed time, carry, roll-down, funding, default, taxes, and transaction costs. Their price changes are conditional rate-risk calculations, not expected investment returns.

## The experiment

The original L2 logistic model uses the curve slope, Chicago Fed credit conditions, and unemployment momentum. The challenger adds one fixed interaction:

`interaction = max(−curve slope, 0) × credit conditions`

The same two-month feature lag, training-only scaling, fixed L2 penalty of 1, annual expanding refits, and thirteen-month eligibility boundary apply to both models. The comparison uses identical mature forecast rows. The target remains **at least one NBER recession month in the following twelve months**, including continuations; it is not recession onset alone.

Negative credit values retain their sign. The interaction coefficient is estimated freely; its final raw coefficient is approximately **−0.5831**. The implementation does not impose a story in which loose credit always dampens an inversion signal. The conditional surface is model geometry, not a causal economic experiment. Its nearby-training counts use distance in the standardized curve–credit plane, within radius 0.35, and ignore labor distance. Sparse input support is a reason for caution, not a confidence interval.

**Selection disclosure:** the interaction, confirmation gate, 50/50 blend, and case windows were developed after examining historical results. Their chronological replay uses correctly sequenced training rows, but the research ideas themselves were not selected before seeing the evaluation sample. They are **post-hoc exploratory hypotheses**, not independent holdout discoveries.

## What the historical comparison actually shows

### Two changes to the next-year forecast

The November 2026 trials test two explanations for persistent overprediction. The **rate-path model** adds changes in interest rates to the existing levels. A widening term spread during rate cuts can carry a different economic interpretation from the same spread during tightening. A Federal Reserve study discusses this ambiguity during 2008. HORIZON uses six-month changes in the ten-year minus three-month spread and twelve-month changes in the effective federal funds rate as its own test of the hypothesis. Both changes use exact observation-month endpoints lagged two months from the forecast issue. [Federal Reserve analysis of the yield curve and recessions](https://www.federalreserve.gov/econres/notes/feds-notes/predicting-recession-probabilities-using-the-slope-of-the-yield-curve-20180301.html)

The five-input logistic uses the original training-only standardization and L2 penalty of one. Its trial probability is the average of that fitted probability and its training prevalence. Comparing the unblended five-input and three-input models on the same training rows isolates the effect of the extra signals. The second hypothesis was specified after evaluating the rate-path trial. It leaves the original model intact and replaces the long historical prevalence in its 50/50 blend with the mean of completed binary targets over a fixed 180-calendar-month issue window. A window ending at the training cutoff requires at least 120 usable rows and 15 years of history. Because each target covers a year, this prevalence differs from the proportion of months spent in recession.

Both trials use an expanding January refit for the historical replay. The last eligible training issue is thirteen months before refitting. The current issue uses a monthly fit and is separately dated. The primary comparison is mean squared probability error (Brier), with log loss and AUC as supporting measures. We compare on identical mature dates over the full replay and since January 2016. The screen calls for lower Brier than the existing 50/50 blend and expanding base in both periods. The recent-frequency control also measures whether the model adds information beyond that frequency alone. The feature lags, blending weights and 15-year length were fixed before evaluating their respective trial. The hypotheses were informed by earlier historical findings. None of these periods provides an untouched prospective test.

In the first replay neither candidate cleared the full screen. Omitting each complete 24-month block and rescoring the remaining fixed predictions shows whether the difference from the incumbent changes sign with the evaluation period. This sensitivity check keeps training fixed and yields no confidence interval. The economic series are revised and the recession dates are retrospective. The prospective ledger begins at actual capture time and allows future observations to be checked independently of this replay. [Open the forecast trial](https://horizon-macro-observatory.samel23.chatgpt.site/#forecast)

### Learning a blend weight from completed forecast windows

For each January, take the original annual-replay probability `p`, its expanding base rate `b` and the binary twelve-month outcome `y` for each eligible earlier issue. Fit `w` to minimize the sum of squared errors for `q = b + w × (p − b)`. The solution is `sum((p − b) × (y − b)) / sum((p − b)²)` clipped to [0, 1]. Identical model and base predictions leave the weight unidentified, in which case the code uses the base rate. Each weight applies to its entire evaluation year within that research vintage.

An issue qualifies for training only when its twelve-month window ends strictly before the January fit and all three values are present. January 1996 was the first fit with 60 eligible months. The January 2026 fit used 420 issues through December 2024 and assigned 46.97% to the original model. Applying that weight to the November 2026 production estimate and base rate gives 22.13%. This illustration uses the current model inputs. Historical evaluation uses the original annual replay. The frozen prospective ledger continues to track its registered fixed 50/50 comparator.

The four methods share a 358-month evaluation sample. Brier scores are 0.19237 (original), 0.17091 (annually fitted), 0.15578 (expanding base) and 0.14855 (fixed 50/50). In 2023 the annual rule still placed 75.26% weight on the original. Across twelve forecast windows that all ultimately contained no recession, the original averaged 91.13%, and the fitted blend averaged 74.71%. Both proposed blends are exploratory. Calendar eligibility removes overlapping training targets from the test boundary. Input revisions and the lag between a turning point and its announcement still limit real-time interpretation. [NBER announcement dates and dating procedure](https://www.nber.org/research/business-cycle-dating/business-cycle-dating-procedure-frequently-asked-questions)

### Original model and interaction candidate over the full historical replay

Same 430 mature monthly issues, January 1990–October 2025; 75 positive forward windows, four independent downturns. Lower Brier and log loss are better; higher AUC is better.

| Comparator | AUC | Brier | Log loss |
| --- | ---: | ---: | ---: |
| Original three-signal model | 0.78216 | 0.17045 | 0.56967 |
| Curve-only model | 0.70971 | 0.17943 | 0.55086 |
| Interaction challenger | 0.78475 | 0.16889 | 0.55942 |
| Expanding historical base rate | 0.36175 | 0.16057 | 0.50590 |
| Exploratory equal-weight original/base-rate blend | 0.76650 | 0.14047 | 0.44630 |

The interaction makes a small historical improvement over the original model. **It still loses to the base rate on probability error.** The blend has better historical Brier and log loss but was proposed after observing overconfidence; it needs an untouched or prospective test. AUC measures ranking and is not classification accuracy.

### Expansion-issued audit: the ranking advantage reverses

The [Model & evidence view](https://horizon-macro-observatory.samel23.chatgpt.site/#model) compares all mature issues with the subset whose issue-month USREC is zero. The latter contains **394 issues and 43 positive forward windows**, versus **430 issues and 75 positive windows** overall; 36 recession-issued rows are excluded. The existing fitted forecasts are reused. This is not a newly trained onset model.

| Comparator | Expansion-issued AUC | Expansion-issued Brier |
| --- | ---: | ---: |
| Original | 0.86524 | 0.14599 |
| Curve only | 0.88054 | 0.14297 |
| Interaction candidate | 0.86524 | 0.14463 |
| Historical base rate | 0.33446 | 0.13169 |
| Exploratory blend | 0.86497 | 0.11252 |

The original model leads curve-only AUC in the all-issue sample, but **curve only ranks better in the expansion-issued sample**. An accuracy claim therefore needs a precise evaluation question and cohort. This restriction uses retrospectively known USREC status and revised history, not information reconstructed as available in real time. It cannot be treated as an operational filter or an untouched selection procedure. AUC and Brier do not change when the alarm threshold changes; threshold-specific warning counts do.

At the illustrative **30%** threshold, the episode audit uses only expansion-issued forecasts strictly within the twelve calendar months before the first USREC = 1 month:

| First USREC = 1 month | Available prior months | First original alarm / lead | First curve alarm / lead | First candidate alarm / lead |
| --- | ---: | --- | --- | --- |
| Aug 1990 | 7/12, partial | Jan 1990 / 7 months | Jan 1990 / 7 months | Jan 1990 / 7 months |
| Apr 2001 | 12/12, complete | May 2000 / 11 months | Apr 2000 / 12 months | May 2000 / 11 months |
| Jan 2008 | 12/12, complete | Jan 2007 / 12 months | Jan 2007 / 12 months | Jan 2007 / 12 months |
| Mar 2020 | 12/12, complete | Mar 2019 / 12 months | Mar 2019 / 12 months | Mar 2019 / 12 months |

The 1990 episode is excluded from complete-window denominators. Each of these three rules has an alarm in **three of three complete windows** at this threshold; the sample does not support a claim of four fully observed successful tests. First USREC = 1 follows the NBER peak month under FRED's convention. Repeated alerts within one downturn do not become independent successful episodes.

### The failure survives

In July 2023, the original model assigned **96.675%** to a recession-positive August 2023–July 2024 window. The interaction challenger assigned **95.840%**. The currently published target is zero. Adding the interaction did not resolve that false alarm.

The supplementary confirmation policy is:

`curve probability ≥ threshold AND (credit > 0 OR labor gap ≥ 0.50 pp)`

It is an alarm rule, not a new probability estimate. At the fixed **30% case-study threshold**:

| Case window | Curve alarms | Withheld by confirmation | Withheld false alarms | Withheld recession-positive windows |
| --- | ---: | ---: | ---: | ---: |
| Financial crisis: Jan 2006–Dec 2009 | 26 | 20 | 12 | 8 |
| Pandemic: Jan 2019–Dec 2021 | 27 | 10 | 1 | 9 |
| Inversion without recession: Jan 2022–Dec 2024 | 28 | 5 | 5 | 0 |

Confirmation removes only five of the 28 curve alarms in the 2022–2024 case. It also withholds eight recession-positive warnings in the financial-crisis case and nine in the pandemic case. The tradeoff matters more than describing the policy as a filter that removes false alarms.

## Decision costs: specify the preference before judging a rule

Let one false alarm cost 1 unit and one missed recession-positive window cost `r` units. For a calibrated binary forecast, the implied alarm threshold is `1 / (1 + r)`. The lab lets the visitor inspect this assumption; it does not claim the fitted models are well calibrated.

At the default **r = 3**, threshold **25%**, all 430 mature rows produce:

| Rule | Alert months | False alarms | Missed windows | Total penalty | Penalty per month |
| --- | ---: | ---: | ---: | ---: | ---: |
| Curve only | 209 | 152 | 18 | 206 | 0.47907 |
| Original model | 180 | 119 | 14 | 161 | 0.37442 |
| Interaction challenger | 180 | 118 | 13 | 157 | 0.36512 |
| Expanding base rate | 372 | 310 | 13 | 349 | 0.81163 |
| Exploratory 50/50 blend | 192 | 130 | 13 | 169 | 0.39302 |
| Curve plus confirmation gate | 96 | 56 | 35 | 161 | 0.37442 |

`penalty per month = (false alarms + r × missed windows) / 430`

The gate cuts curve-only false alarms from 152 to 56 while increasing misses from 18 to 35. The blend's stronger Brier does not guarantee a lower penalty at this particular decision preference. These are **hypothetical utility units, not dollars, trade profits, or investment returns**. Adjacent twelve-month targets overlap. Counts describe recurring monthly forecast windows, not independent bets or separate recession episodes. Choosing the best slider setting after inspecting the table would create another selection problem.

## A prospective record begins after the idea is specified

The prospective recipe is stored in [prospective-protocol.json](prospective-protocol.json). The application freezes the first successful research capture of each new issue month and records its actual timestamp. It does not pretend a receipt captured later in a month was available on the first day, and it does not backfill missed months.

The first published receipt uses September 2026 signals and covers **December 2026–November 2027**. Its `recordedAt` field contains the actual capture timestamp; neither its nominal issue date nor the research build date substitutes for that timestamp:

| Frozen comparator | Probability |
| --- | ---: |
| Original model | 21.1279% |
| Interaction challenger | 20.6699% |
| Historical base rate | 23.0183% |
| Exploratory 50/50 blend | 22.0731% |

At this initial vintage there is **one receipt, zero matured outcomes, and no prospective accuracy result**. Historical replay scores must not be presented as scores earned by this ledger.

Receipts preserve inputs, model parameters, source provenance, recipe/protocol hashes, code-file hashes, the previous receipt hash, and a SHA-256 receipt hash. A CI receipt also records its Git commit; the first local capture has no CI commit and retains explicit code-file hashes instead. Outcome evaluation is stored separately and requires all twelve actually published USREC observations. Later revisions to recession labels remain possible even after a window is scored.

The chain checks consistency of the supplied records. It is **not independent timestamping, a blockchain, or tamper-proof certification**. A maintainer able to replace the whole history could also recompute its hashes. Public Git history provides an additional review trail, with the limitations of that hosting system.

## Reproduce the comparison

```sh
python3 research/build_model.py --offline --as-of 2026-11-25
python3 research/forecast_ledger.py
python3 research/test_model.py
python3 research/test_innovation.py
python3 research/test_forecast_ledger.py
node --test scripts/*.test.mjs
```

Rebuilding the current snapshot can change its research vintage. Existing valid monthly receipts remain frozen. Full source refresh, provider checks, and JavaScript parity checks are run through `bash scripts/refresh-data.sh`; FRED API access can be supplied through the repository Actions secret documented in the README.

Primary foundations: [New York Fed yield-curve research](https://www.newyorkfed.org/research/capital_markets/ycfaq), [Federal Reserve: no single best recession predictor](https://www.federalreserve.gov/econres/notes/feds-notes/there-is-no-single-best-predictor-of-recessions-20190521.html), [Federal Reserve: recession risk and credit sentiment](https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/recession-risk-and-the-excess-bond-premium-20160408.html), [Chicago Fed financial-conditions methodology](https://www.chicagofed.org/research/data/nfci/current-data), and [NBER business-cycle dating](https://www.nber.org/research/business-cycle-dating). These motivate the economic question; they do not certify this project's models or results.

## Does the historical base rate depend on the economic environment?

The economic-regime trial holds the original model forecast and its 50% weight fixed. For the other half, it uses the latest 180 eligible calendar issue months and groups them by credit and labor conditions. Credit is tight above zero on the Chicago Fed credit subindex. Labor is elevated when HORIZON’s smoothed unemployment gap is at least 0.50 percentage points. Both signals precede the forecast issue by two months. Each group’s positive count is pooled with 24 issue-months at the overall recent rate. An empty group therefore receives the recent pooled rate. The regime labels and pooling strength are design choices. [Chicago Fed credit subindex](https://fred.stlouisfed.org/series/NFCICREDIT) · [Civilian unemployment rate](https://fred.stlouisfed.org/series/UNRATE)

Historical fits use only training issues whose 12-month window ends before the January refit. Every prediction uses the same original-model forecast as the incumbent. The decision requires strictly lower mean squared probability error (Brier) in both the full common replay and the last 120 calendar issue months ending at the latest mature incumbent forecast. The positive outcome means that at least one of the next twelve months is classified as a recession, including continuation. Revised data and retrospective business-cycle dating limit what this replay can establish. [Recession indicator and dating convention](https://fred.stlouisfed.org/series/USREC)

The first November 2026 build scored 430 monthly forecasts and 120 in the latest decade. The incumbent scored 0.14047 and 0.17315. Replacing its expanding base with a recent unconditioned base scored 0.14078 and 0.16176. Adding the credit/labor conditioning scored 0.12831 and 0.17338. The changing prevalence alone helped in the recent decade. Conditioning added value across the longer period and gave up that recent gain.

After inspecting the first comparison, a second experiment estimated the reliability of the regime adjustment from earlier out-of-fold forecasts with completed outcomes. Each January it estimates a bounded least-squares weight from at least 60 eligible observations and applies it for the coming year. Until then the recent pooled rate supplies the prior. This adaptation scored 0.13256 and 0.17338. The latest decade contains 13 positive forecast windows overlapping a single recession. The site also scores each calendar issue month separately so readers can compare forecasts with disjoint target windows within each row.

The dedicated archive freezes both candidates and the incumbent together before the forecast window begins. First captures, issue dates, inputs, weights, and outcomes are auditable as the observations mature. [Interactive trial](https://horizon-macro-observatory.samel23.chatgpt.site/#regimes) · [Monthly replay CSV](https://horizon-macro-observatory.samel23.chatgpt.site/api/download?file=regimes) · [Prospective receipts](https://horizon-macro-observatory.samel23.chatgpt.site/api/download?file=regimereceipts)

The exact research files hashed by the first receipt are available in the release history. [First-capture source revision](https://github.com/samuel-mingdao-ma/horizon-macro/tree/75ead8e04bafb9a6ee41e32b61e58a0dd747f185/research)
