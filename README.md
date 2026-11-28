# HORIZON · U.S. Macro Risk Observatory

[Live website](https://horizon-macro-observatory.samel23.chatgpt.site) · [Decision brief](https://horizon-macro-observatory.samel23.chatgpt.site/#brief) · [Model audit](https://horizon-macro-observatory.samel23.chatgpt.site/#model) · [Public source](https://github.com/samuel-mingdao-ma/horizon-macro) · [Refresh history](https://github.com/samuel-mingdao-ma/horizon-macro/actions/workflows/refresh-research.yml)

An updating quantitative research website that asks: **What do the Treasury curve, credit conditions and labor momentum imply about the chance of at least one U.S. recession month in the next twelve months?**

HORIZON combines public Federal Reserve data, interpretable models, chronological validation, an interactive **Alarm Lab**, and frozen prospective forecast receipts. Its central finding is useful precisely because the proposed credit interaction did not cure the historical false alarm. It is a student research project, not an official Federal Reserve forecast. The website is publicly accessible; its source and refresh history are available on GitHub.

## Recession onset from expansion

How often does the extra month of warning survive when both yields move as they have historically? A one-trading-session change in the monthly quote window gives an observable paired perturbation. The site samples these offsets in six-month blocks using only earlier observations and reuses each generated month across overlapping forecasts. In the November 2026 replay, 19,742 of 20,000 histories retained the extra 2001 warning. Just 2,005 also held both Brier scores and both false-alarm limits, a 10.025% joint pass rate. Using only the repriced 30% comparator raises that joint share to 29.33%. Paths, sampling assumptions and alternative comparisons are downloadable. [Empirical yield path simulation](https://horizon-macro-observatory.samel23.chatgpt.site/#pathsimulation)

The joint yield stress test asks whether the extra month of warning before the 2001 recession survives small changes in the source rates. It reprices every forecast and its momentum over four observation months using the model available for that forecast. The May 2000 alert survives ±3 bp in each yield. At ±5 bp the first alert can move back to June. One consistent ±3 bp history triggers a February 2019 false alarm and increases quiet-month warnings from 66 to 67 in the full sample and from 39 to 40 in the recent decade. Persistent curve flattening also raises probability error in both samples. The 30% warning remains the operational benchmark. [Joint yield stress test](https://horizon-macro-observatory.samel23.chatgpt.site/#jointstress)

The warning stability page tests the case-sensitive 2:1 yield rule across four definitions of a flat long yield and five nearby ratios. In the November 2026 replay all 20 rules made the same decisions on observed rates. Twelve still kept the early May 2000 alert and added no false-alert months when the ten-year change could move independently by up to three basis points in every issue. A five-basis-point flat band and a 2:1 ratio pass that test, while a five-basis-point upward shift in February 2019 would already produce an extra warning under that rule. The grid tests decision sensitivity on previously studied forecasts. [Warning stability](https://horizon-macro-observatory.samel23.chatgpt.site/#stability)

The yield-curve study decomposes each three-month spread change into its short-bill and ten-year components. The May 2000 recession warning had 49 basis points of bill-rate increase and 2 basis points of long-rate decline. In February 2019 the figures were 24 and 17. A short-led filter kept the earlier May warning and reduced the pace rule's extra quiet months from eleven to three. A separate 2:1 filter designed after reviewing those cases had zero extra false-alert months in the historical sample. Its single extra hit and the three-basis-point sensitivity of the May decision make prospective testing important. [Yield curve drivers](https://horizon-macro-observatory.samel23.chatgpt.site/#curvelegs)

The signal-confirmation study asks whether building permits, unemployment claims and credit conditions can screen the extra warnings produced by rising risk. In the November 2026 replay, requiring all three pressure signals removed every extra quiet-month warning and also removed the extra month of lead before the 2001 recession. The two historical cases reveal why. The model assigned almost identical contributions to a flattening yield curve, while the economy showed less broad deterioration before the 2001 recession than in the February 2019 false alarm. The evidence page includes the paired input readings, an additive risk decomposition and a monthly audit. [Signal confirmation](https://horizon-macro-observatory.samel23.chatgpt.site/#confirmation)

The risk-momentum experiment tests whether the speed of a rise in recession risk can advance a warning while preserving the expansion model's conditional probabilities. In the November 2026 replay the three-month rule recovered one month of lead before the 2001 recession and added 11 false-alert months across the full history, including six in the recent decade. A stricter one-month rule added six false-alert months and recovered no lead. The 30% level remains the reference warning. The interactive replay shows every extra alert, including a February 2019 reading that exceeded May 2000 on all three risk measures. [Risk momentum and recession timing](https://horizon-macro-observatory.samel23.chatgpt.site/#momentum)

The expansion-onset experiment asks how often the U.S. enters recession in the next twelve months given an expansion at issue. It refits the four-signal permits model and the historical base using only mature expansion-origin forecasts. The November 2026 replay improved paired probability error and reduced quiet-month warnings over both periods. Its first warning in the 2001 episode moved one month later. In the most recent decade, the historical expansion base rate alone scored better than either model and stayed below the alarm threshold throughout. The page compares both forecast components, shows the twelve monthly issues preceding each recession and records conditional forecasts as they are issued. [Expansion-onset experiment](https://horizon-macro-observatory.samel23.chatgpt.site/#onset)

## Credit dynamics

The permits model assigns half its forecast to a ridge-logistic signal and half to the expanding historical base rate. A new trial splits credit into its trailing level and its latest change while keeping this blend fixed. The November 2026 replay removed two quiet-expansion alerts across 430 mature issues. All three other alert changes occurred during the 2007–09 recession. The recent decade had identical alarm decisions and higher probability error for the split model. Each issue, model control, credit state and forecast record can be inspected or downloaded. [Credit dynamics](https://horizon-macro-observatory.samel23.chatgpt.site/#credit)

## What the project demonstrates

- A focused economic question with an explicitly defined forecast target.
- Direct FRED ingestion, observation-date discipline, missing-data handling and a visible fallback when live retrieval fails.
- Training-only standardization, expanding-window estimation and separation of training/test target windows.
- Comparison with a curve-only model and an expanding historical base rate.
- An exploratory curve–credit interaction, a conditional risk surface with historical support counts, and explicit attempts to falsify a proposed improvement.
- A decision brief with reverse-solved credit alarm triggers and a downloadable, dated HTML research memo.
- Expansion-issued versus all-issue evaluation and episode-specific warning lead times with explicit coverage.
- Decision-cost comparisons that expose the price of demanding credit/labor confirmation.
- Frozen monthly forecasts with actual capture timestamps, model/input hashes, separate outcome scoring, and no retrospective filling of missed months.
- Honest interpretation of discrimination, calibration, model failure and conditional sensitivities.
- A React/Vinext interface and Cloudflare Worker API, with downloadable research artifacts.

## Saved research result

The saved research build is dated **25 November 2026**. Its November 2026 model estimate is **21.13%**, using September 2026 features and covering December 2026–November 2027. These are model estimates rather than calibrated guarantees. Live inputs can subsequently change the website's headline.

Evaluation uses 430 mature monthly forecast issues, January 1990–October 2025, with only four independent recession episodes:

| Metric | Three signals | Curve only | Historical base rate |
| --- | ---: | ---: | ---: |
| ROC AUC; higher is better | 0.7822 | 0.7097 | 0.3617 |
| Brier score; lower is better | 0.17045 | 0.17943 | 0.16057 |
| Log loss; lower is better | 0.56967 | 0.55086 | 0.50590 |

The model improves ranking relative to the curve-only comparator but **does not beat the base rate on probability error**. AUC 0.7822 does not mean 78.22% accuracy. A major failure was July 2023: a 96.675% estimate for August 2023–July 2024, while the currently published recession target is zero. This false alarm is retained and explained.

An **exploratory, post-hoc 50/50 blend** of the model and each fold's historical base rate has AUC 0.7665, Brier 0.14047 and log loss 0.44630 on those same 430 months. It illustrates a shrinkage hypothesis, but was proposed after viewing the test results and is **not independently validated**. It does not replace the production headline; future-vintage or untouched-period evaluation is required.

## A view with explicit revision triggers

Open the [Decision brief](https://horizon-macro-observatory.samel23.chatgpt.site/#brief) for the current economic interpretation and a reverse question: **what credit level makes the fitted estimate cross a chosen research alarm?** Hold the labor gap and curve slope fixed, choose a threshold, and solve the logistic model backwards. At the initial September 2026 inputs—curve **1.05 pp**, labor gap **0.00 pp**, credit **−0.03475**—the illustrative **30%** crossing is:

| Model | Required credit index | Shift from current credit |
| --- | ---: | ---: |
| Original | 0.38550 | +0.42025 |
| Interaction candidate | 0.36063 | +0.39538 |

These are **algebraic model crossings, not causal economic tipping points or confidence bounds**. Under inversion the candidate can reverse the sign of its credit sensitivity; an insensitive model has no unique crossing. Nearby-input counts reveal support in the curve–credit plane and do not measure certainty.

[Download the dated HTML memo](https://horizon-macro-observatory.samel23.chatgpt.site/api/brief) (`GET /api/brief`) for the outlook, source dates, caveats, and an exact ±100 bp repricing of an illustrative $1m ten-year semiannual par-coupon bond. The rate shock is separate from recession probability and from the curve-slope control: cash flows stay fixed, with no carry, elapsed time, funding costs, or forecast return. The memo reflects the source snapshot retrieved for that download; it is not a frozen prospective receipt.

## Does the result survive an expansion-only evaluation?

The [Model & evidence audit](https://horizon-macro-observatory.samel23.chatgpt.site/#model) defaults to **expansion-issued only**. Restricting the same originally trained forecasts to issue-month USREC = 0 leaves **394 mature issues and 43 positive forward windows**, compared with **430/75** in the all-issue sample. No onset model is retrained.

| Comparator | Expansion-issued AUC | Expansion-issued Brier |
| --- | ---: | ---: |
| Original | 0.86524 | 0.14599 |
| Curve only | 0.88054 | 0.14297 |
| Interaction candidate | 0.86524 | 0.14463 |
| Historical base rate | 0.33446 | 0.13169 |
| Exploratory blend | 0.86497 | 0.11252 |

**The apparent ranking advantage reverses:** curve-only AUC exceeds the original inside the expansion-issued cohort, although the original leads in the full sample. This is a diagnostic of the question and cohort, not proof of a new strategy. USREC's contemporaneous regime is known retrospectively here; this filter does not recreate information available at issuance.

The episode table examines strictly pre-start expansion forecasts in the preceding twelve months. The first USREC = 1 month in 1990 is **August**; the available history supplies only **7/12** prior months. It is visibly partial and excluded from complete-episode aggregates, which have **three** fully observed episodes. A warning in the partial 1990 case must not be reported as four fully observed successes out of four.

## Alarm Lab: the innovation and its result

The lab asks: **Does requiring credit or labor confirmation make a yield-curve alarm more useful?** It combines a testable statistical hypothesis with a decision audit and a prospective record. This is an original project workflow, not a claim to a new forecasting method.

- **Conditional surface:** add `max(−curve slope, 0) × credit` to the original three inputs; inspect fitted risk while holding labor fixed. The signed interaction coefficient is estimated freely. Historical input dots and nearby-month counts expose weak support; they do not quantify uncertainty or establish causality.
- **Failure replay:** compare the financial crisis, pandemic, and 2023 false alarm. In July 2023, the interaction candidate still assigned **95.84%** to a horizon whose realized recession target was zero, versus **96.68%** originally.
- **Decision costs:** choose a missed-warning/false-alarm cost ratio and inspect counts on the same mature months. At ratio **3**, the illustrative threshold is **25%**. The curve-confirmation gate reduces false alarms from **152 to 56**, but raises missed positive windows from **18 to 35**, relative to the curve alone. Overlapping months are not independent decisions or trades.
- **Prospective receipts:** the first published receipt covers **December 2026–November 2027**. Its `recordedAt` field preserves the actual capture timestamp; consult the receipt for the precise time rather than treating its issue month as a timestamp. The initial ledger has **one receipt and zero matured outcomes**. It freezes the original, interaction, historical-base-rate, and exploratory blend forecasts. No prospective performance has been established.

On the same 430 historical months, the interaction candidate's AUC is **0.7848**, Brier **0.16889**, and log loss **0.55942**. Its small Brier improvement over the original **0.17045** still trails the base rate's **0.16057**. The 50/50 blend's better historical Brier does not make it the best rule under every decision cost: at ratio 3, its penalty per month is **0.3930**, versus **0.3744** for the original and **0.3651** for the interaction candidate.

All new hypotheses were developed after viewing the historical failures. Their chronological replay is **post-hoc exploration, not an untouched test**. Hash linking checks internal consistency; it does not provide independent timestamping, blockchain security, or tamper-proof certification. Read [the experiment, complete comparison, and prospective protocol](research/INNOVATION.md).

## Can the next-year recession forecast be improved?

Two trials address different sources of error. The first adds the six-month change in the Treasury term spread and the twelve-month change in the effective federal funds rate. The second keeps the original three-signal forecast and changes the base rate it is blended with. It gives equal weight to the model and the frequency of positive twelve-month forecast windows among the preceding 15 years of eligible issue months. Both trials predict whether **at least one of the twelve months following issuance is a recession month**. [Explore the forecast trials](https://horizon-macro-observatory.samel23.chatgpt.site/#forecast)

In the November 2026 build, the rate-path blend scored **0.14319 Brier** over 430 mature issues and the recent-base blend scored **0.14078**. The existing 50/50 blend scored **0.14047**, with lower scores indicating smaller probability errors. From January 2016 onward, the recent-base blend improved on the existing blend (**0.16405 versus 0.17562**), while its 15-year historical frequency alone scored **0.11412**. This suggests that the choice of historical base rate deserves as much attention as adding another market signal. The page lets readers check sensitivity to omitting a two-year period and examine each forecast. [Download the annual replay](https://horizon-macro-observatory.samel23.chatgpt.site/api/download?file=ratepath)

The current trial estimates and incumbent are also archived together at their first eligible capture in each issue month. Future scoring requires twelve observed recession labels. This archive has its own forecast records and research recipe. [Download the prospective trial receipts](https://horizon-macro-observatory.samel23.chatgpt.site/api/download?file=ratepathreceipts)

## What does a 21% forecast mean in practice?

The November 2026 original estimate is 21.1% for December 2026 through November 2027. In the comparable historical replay, 48 original estimates fell in its 20–40% band. Their mean forecast was 27.4%, and 4 of the 48 forward windows contained a recession (8.3%). The windows overlap and the band spans a range of economic conditions. Its observed rate provides historical context for the current estimate. [Inspect the probability bands](https://horizon-macro-observatory.samel23.chatgpt.site/#calibration)

Each January, the experiment estimates how much weight to give the original model relative to its expanding base rate. Weights use only earlier forecast issues whose twelve-month outcome windows ended before that January, with at least 60 usable observations. On the same 358 mature issues from January 1996 through October 2025, mean squared probability error (Brier score) was 0.19237 for the original, 0.17091 for the fitted blend, 0.15578 for the base rate and 0.14855 for the existing fixed 50/50 blend. The fitted weight improves on the original while both simpler alternatives score better. The protocol was explored after historical errors were visible. [Download all 358 forecasts and their training cutoffs](https://horizon-macro-observatory.samel23.chatgpt.site/api/download?file=probability)

## How long does a false warning last?

In the November 2026 replay, the original model signaled every month from September 2022 through February 2026 at a 30% threshold. Of those 42 forecasts, the first 38 had completed twelve-month windows with no recession. The last four outcomes were pending. The longest confirmed false-warning streak was therefore **at least 38 months**. This one stretch accounts for 38 of the original model’s 107 mature false-warning months. [Explore the original model’s alarm history](https://horizon-macro-observatory.samel23.chatgpt.site/#history?rule=original&threshold=30)

Requiring credit or labor confirmation cut the longest observed false-warning streak to **21 months**. That filter also flagged fewer recession-positive windows than the curve rule it modifies, **36 of 75 versus 53 of 75**. The calendar lets readers inspect individual months, vary the threshold, and download the underlying evidence. Each forecast covers the following twelve months, so consecutive results overlap. [Explore the confirmation rule](https://horizon-macro-observatory.samel23.chatgpt.site/#history?rule=gate&threshold=30)

## Run locally

Prerequisites: Node.js **22.13 or later**, npm, Python **3.12 recommended**, and Git. No FRED API key is needed for the chart CSV endpoint used here.

```sh
npm run install:ci
npm run dev
```

Open the loopback URL printed by the development server, normally `http://localhost:5173`. To choose a port:

```sh
npm run dev -- --port 5174
```

Build and preview the production Worker locally:

```sh
npm run build
npm start
```

`npm start` prints its own preview URL. It does not deploy the site. When publishing through Sites, use the Sites build/package/publish workflow and retain `.openai/hosting.json`.

## Rebuild and verify the research

```sh
python3 -m pip install numpy==2.1.3 pandas==2.2.3 requests==2.32.3
python3 research/build_model.py --refresh
python3 research/forecast_ledger.py
python3 research/test_model.py
python3 research/test_innovation.py
python3 research/test_forecast_ledger.py
node --test scripts/*.test.mjs
```

For an offline reconstruction using the saved raw observations:

```sh
python3 research/build_model.py --offline --as-of 2026-11-25
```

The Python tests verify target timing, unavailable future labels, training eligibility, training-only scaling, equivalent scoring/decomposition, numerical estimation, credit aggregation and missing labor observations. Additional checks recompute candidate metrics, fixed case subsets, confirmation rules, surface support, inverse credit crossings, cohort scores, episode coverage, receipt hash integrity, and separate outcome maturation. Use the current command output for test counts; they change as coverage grows. The Node tests verify Python/JavaScript parity and live-inference behavior. Neither test suite establishes predictive profitability.

## How updates work

The public portfolio repository is [samuel-mingdao-ma/horizon-macro](https://github.com/samuel-mingdao-ma/horizon-macro). Two independent paths keep the website current:

| Path | Behavior |
| --- | --- |
| GitHub Actions research refresh | Fetches full FRED history, refits the models, recomputes chronological validation, freezes the first successful capture of each new issue month, evaluates previously frozen outcomes separately, runs Python/JavaScript checks, and commits the verified artifacts at **18:30 UTC each weekday**. Manual workflow runs are supported. |
| Production `/api/macro` | Checks the repository's published research snapshot with a one-hour cache. It validates dates, model parameters, and scoring before serving it. Updated data and model coefficients therefore reach the hosted website without a source redeploy. If GitHub is unavailable, it tries direct FRED scoring, then retains a clearly dated fallback. |

When cloud access to the FRED graph download is unavailable, the pipeline verifies the same core level series using the official [FRED-MD release](https://www.stlouisfed.org/research/economists/mccracken/fred-databases) and [Chicago Fed credit CSV](https://api.data.chicagofed.org/NFCI/nfci-data-series-csv.csv). It preserves later cached observations, retains dated USREC/unsupported-tenor caches, and never invents new recession labels. Evaluation can therefore remain at its last known label cutoff while current signals advance. `meta.dataRefresh.perSeries` records retrieval and cache provenance; original fallback responses are retained in `research/provider-cache/`.

The browser checks on load, when returning to the tab, and every six hours. Source checks are not market ticks. GitHub schedules may be delayed or disabled; the last research-build timestamp and observation months remain the freshness evidence. Visit the repository's **Actions → Refresh HORIZON research** to inspect actual successful runs. No API key or hosting secret is required for the official fallback. An optional repository secret `FRED_API_KEY` enables the documented FRED API transport and can refresh series unavailable through alternative feeds. Never commit a key to source.

When forking this project, change `RESEARCH_SNAPSHOT_URL` in `lib/live-data.ts` to your repository's raw snapshot URL, enable Actions with `contents: write`, and manually run the workflow once. Keep the Sites source remote and the GitHub portfolio remote separate. CSV downloads also follow the verified research snapshot; the ZIP source export is the website release source, while GitHub is the newest source.

## Cloud source access

**Verified 25 November 2026:** [cloud refresh 45710561484](https://github.com/samuel-mingdao-ma/horizon-macro/actions/runs/45710561484) completed successfully, fetched all eleven series through the official FRED API, passed its checks, and committed the refreshed research. The key is stored in the repository Actions secret; it is absent from public source and artifacts.

The website is public and its API/download routes are verified. Cloud runners can time out when accessing FRED graph downloads and the FRED-MD website. The full-refresh workflow therefore also supports the documented FRED API via the repository secret `FRED_API_KEY`.

1. Request your own key through the [official FRED API key page](https://fred.stlouisfed.org/docs/api/api_key.html).
2. In [GitHub Actions secrets](https://github.com/samuel-mingdao-ma/horizon-macro/settings/secrets/actions), create `FRED_API_KEY`. Enter the key there, never in source or a chat message.
3. Run [Refresh HORIZON research](https://github.com/samuel-mingdao-ma/horizon-macro/actions/workflows/refresh-research.yml) and confirm a successful complete run and resulting research commit.
4. The hosted site will read the resulting public research snapshot on its next hourly check; no hosting redeploy is required.

A configured schedule alone is not proof of a successful refresh. The linked run is the verified example; continue using actual observation dates and successful-run history as the freshness evidence.

## Methods and important limits

Predictors at issue month `t` use observations from `t−2`:

- **Curve:** GS10 minus TB3MS, in percentage points. These have different quote bases; this is the project's proxy, not an exact NY Fed replication.
- **Credit:** monthly arithmetic mean of weekly Chicago Fed NFCICREDIT observations. It is a conditions index, not a traded bond spread.
- **Labor:** three-calendar-month unemployment mean minus the trailing twelve-month minimum of such means. At least two observations are required per three-month mean; no missing rate is interpolated.

The target is any USREC recession month in `t+1` through `t+12`, including continuation of an existing recession. The model uses a fixed L2 penalty of 1, an unpenalized intercept, and annually refitted expanding training samples for historical evaluation. Training issue dates end at least thirteen months before each January refit; a stricter twenty-five-month sensitivity is also supplied.

This is a **latest-vintage historical simulation**, not a historical real-time vintage backtest. Revised unemployment/NFCI history and retrospective NBER dating remain limitations. Twelve-month targets overlap, so hundreds of monthly forecasts do not represent hundreds of independent business cycles. The fitted labor coefficient is near zero and slightly negative; conditional model coefficients are not causal economic effects.

October 2025 UNRATE and CPI observations are missing in the official source. The available-observation labor policy handles the former explicitly; October 2026 CPI year-over-year inflation cannot be computed from a missing year-ago denominator, so the latest valid inflation value retains its own date.

Read [the full methodology](research/METHODOLOGY.md), [Alarm Lab research](research/INNOVATION.md), and [source audit notes](research/source-notes.md) for formulas, exact clock conventions, failure analysis and attribution.

## Should the model’s weight change with the economy?

The adaptive-weight trial compares six forecasts on identical issue months. The primary model learns how much weight to give the permits-augmented signal from completed earlier forecasts in two observable credit and yield-curve states. Compare full and trailing-decade probability errors, false alarms, and first or newly triggered recession warnings at a fixed 30% threshold. The issue explorer shows the weights available when each forecast was made. [Interactive trial](https://horizon-macro-observatory.samel23.chatgpt.site/#weights) · [Research design and evidence](research/INNOVATION.md#changing-the-signal-weight-by-economic-state)

## Early warning from building permits and initial claims

The Before recession view traces each forecast back to the signals available two months earlier. It compares housing permits and initial unemployment claims against the existing 50/50 forecast using exactly the same months, historical base probability, model penalty and target. The page separates forecasts issued before recession onset from those issued during a recession, and shows calibration across all expansion issues. [Open the leading-indicator trial](https://horizon-macro-observatory.samel23.chatgpt.site/#leading) · [Read the evidence](research/INNOVATION.md#what-was-visible-before-recession-onset) · [Issue-level CSV](https://horizon-macro-observatory.samel23.chatgpt.site/api/download?file=leading)

## Economic-regime base rates

Can a changing base rate improve the 12-month forecast? The regime trial keeps the original model at 50% and compares an expanding historical base with a recent credit-and-labor-conditioned base. The annual walk-forward replay reports errors on identical months across the full sample and latest ten years. Readers can inspect all four state counts, compare unconditioned and adaptive alternatives, and audit frozen forecasts as outcomes mature. [Open the experiment](https://horizon-macro-observatory.samel23.chatgpt.site/#regimes) · [Model design and initial results](research/INNOVATION.md#does-the-historical-base-rate-depend-on-the-economic-environment)

## Architecture and research files

```text
app/page.tsx                 server entry and initial research snapshot
app/dashboard.tsx            navigation and original research views
app/alarm-lab.tsx            conditional surface, cases, costs and receipt UI
app/decision-brief.tsx       economic view and reverse credit triggers
app/warning-audit.tsx        expansion cohorts and pre-episode warning coverage
app/api/macro/route.ts       live snapshot endpoint
app/api/download/route.ts    JSON/CSV download endpoints
app/api/brief/route.ts       dated, downloadable HTML research memo
lib/risk-triggers.ts        validated inverse-logistic credit crossings
lib/warning-audit.ts        retrospective cohort and episode diagnostics
lib/live-data.ts             FRED parsing, alignment, scoring and fallback
research/build_model.py     full-history estimation and validation
research/test_model.py      quantitative invariants
research/innovation.py      exploratory interaction and case diagnostics
research/forecast_ledger.py frozen receipts and separate outcome evaluation
research/test_innovation.py challenger and historical-replay checks
research/test_forecast_ledger.py receipt and protocol checks
research/prospective-protocol.json fixed prospective comparison recipe
data/forecast-ledger.jsonl append-only monthly receipt records
research/raw/               cached series used for reproducible research
research/provider-cache/    original official fallback files and provenance
research/folds.json         historical train/refit boundary audit
data/snapshot.json          canonical bundled research snapshot
public/data/                browser fallback and downloadable CSV files
.github/workflows/          weekday scheduled research rebuild
worker/index.ts             production Worker entry
```

The macro API serves the latest validated scheduled research build, with direct-input inference as a fallback. Public CSVs identify their research vintage. Historical annual predictions and the current monthly production refit are separately labeled. Log-odds contributions reconstruct the current probability exactly; they are not additive probability-point effects. Scenario outputs are conditional model sensitivities, not causal forecasts.

Sources are attributed to the Federal Reserve Board, Chicago Fed, BLS, St. Louis Fed and NBER through the exact FRED series URLs in the snapshot. No synthetic observation is substituted for provider data. See [the Chinese submission guide](SUBMISSION_GUIDE.md) for presentation and interview preparation.
