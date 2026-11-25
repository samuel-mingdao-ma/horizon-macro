# HORIZON: source and interpretation notes

Research checked 25 November 2026. These notes distinguish provider definitions from project choices. This is a student research model; the project is not a Federal Reserve forecast.

## Primary sources

| Series or research | Definition and use | Primary source |
| --- | --- | --- |
| GS10 | Monthly average ten-year constant-maturity Treasury yield; percent, investment basis. Federal Reserve H.15. | [FRED: GS10](https://fred.stlouisfed.org/series/GS10) |
| TB3MS | Monthly average three-month Treasury bill secondary-market rate; percent, discount basis. Federal Reserve H.15. | [FRED: TB3MS](https://fred.stlouisfed.org/series/TB3MS) |
| UNRATE | Monthly seasonally adjusted civilian unemployment rate, U-3; percent. BLS Current Population Survey. | [FRED: UNRATE](https://fred.stlouisfed.org/series/UNRATE) |
| USREC | St. Louis Fed interpretation of NBER chronology; 1 denotes recession. Includes the month after the peak through the trough month. | [FRED: USREC](https://fred.stlouisfed.org/series/USREC) |
| CPIAUCSL | Monthly seasonally adjusted all-items CPI index. Use 100 × (index / index twelve months earlier − 1) for twelve-month inflation. | [FRED: CPIAUCSL](https://fred.stlouisfed.org/series/CPIAUCSL) |
| NFCICREDIT | Chicago Fed weekly credit-conditions subindex. Positive values indicate tighter credit conditions than average; negative values indicate looser conditions. | [FRED: NFCICREDIT](https://fred.stlouisfed.org/series/NFCICREDIT) |
| National Financial Conditions Index | Financial-conditions methodology, publication schedule, and current data. | [Chicago Fed: current data](https://www.chicagofed.org/research/data/nfci/current-data) |
| NY Fed yield-curve model | A probit framework based on ten-year minus three-month rates, estimating recession status twelve months ahead. Its target differs from an any-month-within-twelve-months target. | [New York Fed: Yield Curve as a Leading Indicator](https://www.newyorkfed.org/research/capital_markets/ycfaq) |
| Credit and recession research | Research showing that credit-market risk appetite can carry information about subsequent recession risk, with false positives and false negatives. It does not validate any other specific credit proxy. | [Federal Reserve: Recession Risk and the Excess Bond Premium](https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/recession-risk-and-the-excess-bond-premium-20160408.html) |
| Predictor selection | Predictive usefulness differs by forecasting horizon; additional predictors require empirical comparison. | [Federal Reserve: There is No Single Best Predictor of Recessions](https://www.federalreserve.gov/econres/notes/feds-notes/there-is-no-single-best-predictor-of-recessions-20190521.html) |
| Business-cycle dating | NBER chronology is retrospective. Turning-point announcements arrive after the economic event and the delay varies. | [NBER: dating FAQ](https://www.nber.org/research/business-cycle-dating/business-cycle-dating-procedure-frequently-asked-questions), [NBER: announcements](https://www.nber.org/research/business-cycle-dating/business-cycle-dating-committee-announcements) |
| Real-time Sahm indicator | Three-month unemployment average relative to the minimum three-month average in the preceding twelve months; the conventional trigger is 0.50 percentage points. | [FRED: SAHMREALTIME](https://fred.stlouisfed.org/series/SAHMREALTIME) |

## Implementation decisions and audit concerns

### Be precise about the event being forecast

For issue month t, define y(t) = 1 if USREC is 1 in at least one month t+1 through t+12, and 0 only if all twelve observations are available and are 0. This includes the continuation of an existing recession. It does not exclusively estimate recession onset, recession severity, negative GDP growth, or recession status exactly twelve months ahead. The site's headline, legends, tooltips, exports, and report should use the same event definition.

### Rates have different quotation conventions

GS10 is quoted on an investment basis; TB3MS uses the bank-discount convention. Their raw difference is a useful project proxy, but it is not the exact New York Fed term spread. The [NY Fed methodology FAQ PDF](https://www.newyorkfed.org/medialibrary/media/research/capital_markets/ycfaq.pdf) specifies a bond-equivalent three-month yield. A curve-only logistic model trained here should be called the project's curve-only benchmark. It should not be labeled the official NY Fed model or an exact reproduction.

### Distinguish a labor feature from the published Sahm rule

A labor-gap feature computed from today's revised UNRATE history is Sahm-style, not the published real-time SAHMREALTIME series. The latter preserves unemployment information available in each historical month. If the trailing minimum includes the current month, the feature is constrained to be nonnegative; a preceding-twelve-month minimum can produce small negative readings when a new low is reached. State the exact window convention in code and methods. Its original economic role is an early recession-detection signal; using it as a twelve-month predictive covariate requires empirical validation.

### Timestamp discipline

Features available for issue month t use source observations no later than t−2. Keep missing months missing; do not silently substitute older values or forward-fill. Lagging by two months is a conservative release-availability proxy, not proof of real-time information availability. For weekly credit data, define the aggregation explicitly, require a complete source month, and retain its final source week and retrieval timestamp. Display the model issue date, source observation month, last successful retrieval, and model training date separately.

### Walk-forward evaluation

Use an expanding training sample, train the scaler only on each training fold, and hold model settings fixed. For each test issue month, training targets must end before the test issue date. For a twelve-month target, a training issue date at least thirteen months earlier is a simple strict rule. Annual refitting is reasonable if disclosed. Compare against an expanding historical base-rate forecast and a curve-only model using exactly the same test rows. Report Brier score, log loss, ROC AUC, calibration, and test-period coverage. Accuracy alone is unsuitable for a rare event.

Monthly twelve-month outcomes overlap. Hundreds of observations do not provide hundreds of independent recession episodes. From 1990 onward there are only four distinct NBER recessions in the available chronology: 1990–91, 2001, 2007–09, and 2020. Avoid ordinary independent-month standard errors and confidence intervals. If intervals are implemented, use a justified time-block or cycle-based method and describe it.

### Latest-vintage simulation limitation

Today's revised data and retrospectively dated recession labels are used throughout history. A chronological train/test split prevents some forms of leakage but does not recreate historical data vintages. NBER declaration delays can make a target unavailable even after its twelve-month horizon has elapsed. Label reported performance as a latest-vintage historical simulation, never a real-time backtest. A stronger future version would use ALFRED vintages and actual announcement calendars. NFCI history itself changes when incoming data or revisions arrive, as the [Chicago Fed FAQ](https://www.chicagofed.org/-/media/publications/nfci/nfci-faqs-pdf.pdf) explains.

### Stress testing is conditional, not causal

Changing one input while holding the rest fixed reveals the fitted model's conditional sensitivity. It does not estimate what a Fed cut or a credit shock would cause in the economy. A steeper curve can reflect rising long yields or falling short yields; those mechanisms need not carry the same economic interpretation. If adding bond repricing, distinguish a parallel yield shock from a curve-slope shock. Compute present values from contractual cash flows and label synthetic illustrative instruments clearly.

### Public dataset reuse

The FRED pages for [Moody's BAA](https://fred.stlouisfed.org/series/BAA) and [Moody's AAA](https://fred.stlouisfed.org/series/AAA) contain explicit restrictions on reproducing and redistributing Moody's information. They are not appropriate raw downloadable public project data without the needed rights. NFCICREDIT is marked citation-required on FRED and is a practical research alternative with attribution. It measures credit conditions and must not be renamed a corporate bond spread. All provider series should retain attribution and source URLs.

## Suggested concise site copy

**Research question.** What do the yield curve, credit conditions, and labor-market deterioration jointly imply about the chance of at least one U.S. recession month in the coming year?

**Why three signals?** The curve summarizes the pricing of money across maturities. Credit conditions capture the availability and price of financing. Labor deterioration checks whether weakness is reaching households. Agreement across them is useful context; disagreement is a research finding to explain.

**How to read the number.** This is a model estimate of one defined economic event, based on three lagged signals. It is not a certainty, an investment return forecast, or a measure of recession severity.

**Historical evidence.** Every displayed evaluation prediction is generated after fitting only to earlier eligible rows. The data are today's revised history, so the exercise is a latest-vintage historical simulation. It does not reproduce what an investor actually knew on each date.

**Model drivers.** Contributions are additive in log odds relative to the fitted model's average input, not additive percentage-point causes of recession probability.

**What would change the view?** A wider credit constraint, a larger unemployment gap, or a different curve slope changes the conditional model estimate. Use the scenario controls to inspect that sensitivity, then ask whether the combination is economically plausible.

## Chinese interview explanation

我的项目把“美国未来一年经济风险”变成了一个可验证的问题：在未来十二个月里，是否至少有一个月份会被 NBER 认定为衰退。利率曲线提供市场预期，信用条件提供融资约束，失业率变化提供实体经济确认。

我没有用随机切分训练集来制造漂亮的准确率，而是按时间顺序滚动估计，并把预测目标覆盖的十二个月从训练边界里剔除。模型和历史基础概率、单一利率曲线模型进行同样区间的比较。评分看概率是否可靠，而不只是分类是否猜对。

最需要讲清楚的限制是历史数据经过修订、NBER 确认存在延迟、样本中独立衰退次数很少。因此结果是“使用当前版本数据的历史模拟”，并不等于已经证明的实时交易优势。项目的价值在于把数据、模型、验证、可解释性和网站更新连成一个可以检查的完整系统。
