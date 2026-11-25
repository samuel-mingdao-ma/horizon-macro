# HORIZON · U.S. Macro Risk Observatory

[Live website](https://horizon-macro-observatory.samel23.chatgpt.site) · [Public source](https://github.com/samuel-mingdao-ma/horizon-macro) · [Refresh history](https://github.com/samuel-mingdao-ma/horizon-macro/actions/workflows/refresh-research.yml)

An updating quantitative research website that asks: **What do the Treasury curve, credit conditions and labor momentum imply about the chance of at least one U.S. recession month in the next twelve months?**

HORIZON combines public Federal Reserve data, an interpretable logistic model, chronological validation, scenario analysis and transparent research downloads. It is a student research project, not an official Federal Reserve forecast. The website is publicly accessible; its source and refresh history are available on GitHub.

## What the project demonstrates

- A focused economic question with an explicitly defined forecast target.
- Direct FRED ingestion, observation-date discipline, missing-data handling and a visible fallback when live retrieval fails.
- Training-only standardization, expanding-window estimation and separation of training/test target windows.
- Comparison with a curve-only model and an expanding historical base rate.
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
python3 research/test_model.py
node --test scripts/refresh-data.test.mjs
```

For an offline reconstruction using the saved raw observations:

```sh
python3 research/build_model.py --offline --as-of 2026-11-25
```

The Python tests verify target timing, unavailable future labels, training eligibility, training-only scaling, equivalent scoring/decomposition, numerical estimation, credit aggregation and missing labor observations. The Node tests verify Python/JavaScript parity and live-inference behavior. Neither test suite establishes predictive profitability.

## How updates work

The public portfolio repository is [samuel-mingdao-ma/horizon-macro](https://github.com/samuel-mingdao-ma/horizon-macro). Two independent paths keep the website current:

| Path | Behavior |
| --- | --- |
| GitHub Actions research refresh | Fetches full FRED history, refits the model, recomputes chronological validation, runs Python/JavaScript checks, and commits the verified artifacts at **18:30 UTC each weekday**. Manual workflow runs are supported. |
| Production `/api/macro` | Checks the repository's published research snapshot with a one-hour cache. It validates dates, model parameters, and scoring before serving it. Updated data and model coefficients therefore reach the hosted website without a source redeploy. If GitHub is unavailable, it tries direct FRED scoring, then retains a clearly dated fallback. |

When cloud access to the FRED graph download is unavailable, the pipeline verifies the same core level series using the official [FRED-MD release](https://www.stlouisfed.org/research/economists/mccracken/fred-databases) and [Chicago Fed credit CSV](https://api.data.chicagofed.org/NFCI/nfci-data-series-csv.csv). It preserves later cached observations, retains dated USREC/unsupported-tenor caches, and never invents new recession labels. Evaluation can therefore remain at its last known label cutoff while current signals advance. `meta.dataRefresh.perSeries` records retrieval and cache provenance; original fallback responses are retained in `research/provider-cache/`.

The browser checks on load, when returning to the tab, and every six hours. Source checks are not market ticks. GitHub schedules may be delayed or disabled; the last research-build timestamp and observation months remain the freshness evidence. Visit the repository's **Actions → Refresh HORIZON research** to inspect actual successful runs. No API key or hosting secret is required for the official fallback. An optional repository secret `FRED_API_KEY` enables the documented FRED API transport and can refresh series unavailable through alternative feeds. Never commit a key to source.

When forking this project, change `RESEARCH_SNAPSHOT_URL` in `lib/live-data.ts` to your repository's raw snapshot URL, enable Actions with `contents: write`, and manually run the workflow once. Keep the Sites source remote and the GitHub portfolio remote separate. CSV downloads also follow the verified research snapshot; the ZIP source export is the website release source, while GitHub is the newest source.

## Cloud source access

The website is public and its API/download routes are verified. Cloud runners can time out when accessing FRED graph downloads and the FRED-MD website. The full-refresh workflow therefore also supports the documented FRED API via the repository secret `FRED_API_KEY`.

1. Request your own key through the [official FRED API key page](https://fred.stlouisfed.org/docs/api/api_key.html).
2. In [GitHub Actions secrets](https://github.com/samuel-mingdao-ma/horizon-macro/settings/secrets/actions), create `FRED_API_KEY`. Enter the key there, never in source or a chat message.
3. Run [Refresh HORIZON research](https://github.com/samuel-mingdao-ma/horizon-macro/actions/workflows/refresh-research.yml) and confirm a successful complete run and resulting research commit.
4. The hosted site will read the resulting public research snapshot on its next hourly check; no hosting redeploy is required.

A configured schedule is not proof of a successful refresh. Until a successful cloud run is recorded, the published data remains a dated research build; use the actual observation dates and refresh history as evidence.

## Methods and important limits

Predictors at issue month `t` use observations from `t−2`:

- **Curve:** GS10 minus TB3MS, in percentage points. These have different quote bases; this is the project's proxy, not an exact NY Fed replication.
- **Credit:** monthly arithmetic mean of weekly Chicago Fed NFCICREDIT observations. It is a conditions index, not a traded bond spread.
- **Labor:** three-calendar-month unemployment mean minus the trailing twelve-month minimum of such means. At least two observations are required per three-month mean; no missing rate is interpolated.

The target is any USREC recession month in `t+1` through `t+12`, including continuation of an existing recession. The model uses a fixed L2 penalty of 1, an unpenalized intercept, and annually refitted expanding training samples for historical evaluation. Training issue dates end at least thirteen months before each January refit; a stricter twenty-five-month sensitivity is also supplied.

This is a **latest-vintage historical simulation**, not a historical real-time vintage backtest. Revised unemployment/NFCI history and retrospective NBER dating remain limitations. Twelve-month targets overlap, so hundreds of monthly forecasts do not represent hundreds of independent business cycles. The fitted labor coefficient is near zero and slightly negative; conditional model coefficients are not causal economic effects.

October 2025 UNRATE and CPI observations are missing in the official source. The available-observation labor policy handles the former explicitly; October 2026 CPI year-over-year inflation cannot be computed from a missing year-ago denominator, so the latest valid inflation value retains its own date.

Read [the full methodology](research/METHODOLOGY.md) and [source audit notes](research/source-notes.md) for formulas, exact clock conventions, failure analysis and attribution.

## Architecture and research files

```text
app/page.tsx                 research interface and interactions
app/api/macro/route.ts       live snapshot endpoint
app/api/download/route.ts    JSON/CSV download endpoints
lib/live-data.ts             FRED parsing, alignment, scoring and fallback
research/build_model.py     full-history estimation and validation
research/test_model.py      quantitative invariants
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
