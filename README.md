# SaaS revenue analytics — synthetic B2B subscription data

A full analytics pipeline over a fictional B2B SaaS business: generate the data, clean it, explain
revenue, predict churn, segment the customer base, and present it in an interactive dashboard.

**Stack:** Python 3.13 · pandas · NumPy · scikit-learn · statsmodels · XGBoost · SciPy · Plotly ·
Dash · SQLite · matplotlib · seaborn

**Data:** synthetic, 200 customers over 4 months, every file at or below 800 rows
**Cost to run:** zero — no API keys, no paid services, fully offline

---

## Build status

| # | Step | File | State |
| --- | --- | --- | --- |
| 1 | Synthetic star schema, defect injection, SQLite load | `config.py`, `data_gen.py` | **complete** |
| 2 | SQL joins, cleaning, invoice reconciliation, EDA, figures | `analysis.py` | **complete** |
| 3 | Regression — what drives revenue, and what cannot be modelled | `analysis.py` | **complete** |
| 4 | Classification — churn prediction and the decision threshold | `analysis.py` | **complete** |
| 5 | Clustering — KMeans, DBSCAN, HDBSCAN, PCA, t-SNE, UMAP | `analysis.py` | **complete** |
| 6 | Interactive dashboard | `dashboard.py` | **complete** |
| 7 | Orchestration | `main.py` | **complete** |
| 8 | Deployment to Hugging Face Spaces | `Dockerfile`, `deploy/huggingface/` | **prepared — first deploy pending** |

**Current state: steps 1–7 complete, step 8 prepared.** The pipeline runs end to end, produces **22 figures** and a single
`reports/results.json`, and passes **40 tests**. The code is on GitHub and in sync; the container has not
been built yet, because that needs a hosting account.

```bash
make all        # the whole pipeline in one command
make test       # 40 tests
make serve      # start the dashboard at http://127.0.0.1:8050
```

---

## The scenario

**Northwind Analytics** is a fictional B2B SaaS company selling seat-based subscriptions. We observe
**200 customers over 4 months of 2026**. Some of them leave.

Four questions, answered in order:

| | Question | Method |
| --- | --- | --- |
| 1 | What does the revenue base look like? | SQL, EDA, distribution analysis |
| 2 | What drives monthly recurring revenue? | Regression |
| 3 | Which customers are about to leave? | Classification |
| 4 | Are there natural customer segments? | Clustering |

## The data

A **star schema** — one fact table and five dimensions, every file under the 800-row cap:

| Table | Rows | What one row is |
| --- | --- | --- |
| `fact_subscription_monthly` | 749 *(737 after cleaning)* | one customer, in one month |
| `dim_customer` | 200 | one customer |
| `dim_rep` | 8 | one sales rep |
| `dim_region` | 6 | one sales territory |
| `dim_plan` | 6 | one subscription tier |
| `dim_date` | 4 | one month in the window |

Written as CSVs, as a SQLite database for real joins, and as a zip bundle.

The fact table holds **749 rows as generated**, including the 12 duplicated rows injected as a defect.
Cleaning removes them, leaving **737**. Both numbers appear throughout the project's output, so the
distinction is worth stating once: 749 is what the generator writes, 737 is what the analysis uses.

Provenance and the sampling rule: [`data/README.md`](data/README.md).

### Two design decisions worth knowing

**The features genuinely cause churn.** Usage, tickets, discount and sentiment are generated first;
churn is derived *from* them by a logistic process whose coefficients are declared openly in
[`config.py`](config.py) (`TRUE_CHURN_COEFFICIENTS`). The tempting alternative — decide who leaves,
then generate that customer's usage to "look churny" — produces circular data where the features are
drawn *from* the label. A model trained on it scores a meaningless 0.99 ROC-AUC. Because causality
runs the right way here, the analysis can honestly ask whether the fitted model **recovered the
process that generated the data** — something a real dataset cannot offer.

**Churn is never a column.** A boolean `is_churned` on a January fact row would mean that row already
"knew" the customer left in March. Churn is derived instead, from the panel structure: a customer whose
last observed month precedes the final month has left. This is asserted by a test. `churn_reason_id` is
post-hoc and confined to `dim_customer`.

### Deliberate defects

Eight documented faults are injected, light enough that the analysis is not swamped and specific
enough that cleaning has real work to do. Every one is recorded in `reports/data_quality.json` with its
size and what it breaks.

| Defect | Rows | What it breaks |
| --- | --- | --- |
| Duplicated fact rows | 12 | Double-counts revenue and inflates every total |
| Blank `usage_events` | 18 | Biases any mean computed by dropping rows |
| Negative `usage_events` | 4 | Impossible values drag averages down |
| Discount above 100% | 5 | Produces negative MRR |
| Mixed date formats | 8 | `pd.to_datetime` parses inconsistently |
| Blank `industry` | 6 | Cannot group by industry until imputed |
| Blank `region_id` | 3 | **A broken foreign key** — an inner join silently drops these customers |
| Rep hired after signup | 4 | Temporal impossibility |

---

## Findings

### Headline numbers

**Revenue is falling, and churn is the reason.** MRR declines from **$1,148,753 in January to $854,944
in April** — **−25.6% over four months**. That single fact is what makes the rest of the analysis worth
doing, and it is the first thing the dashboard will show.

**40 of 200 customers left** — an overall churn rate of **20.0%** across the window.

**The data was cleaned before anything was counted.** Eight deliberate defects were repaired: 12
duplicated rows dropped, 18 blanks and 4 impossible values imputed from the median, a discount above
100% corrected, three broken foreign keys fixed, and a temporal impossibility flagged. Each repair is
logged with its size and reasoning in `reports/data_quality.json`.

**The invoice arithmetic reconciles.** `mrr = seats × list price × (1 − discount)` holds within 5% on
**90.6%** of rows, with a median difference of **2.0%**. Real finance teams check this every month, and
it is the one relationship in the data with an exact expected answer.

### 1. Three times, the apparent pattern was not one

The most valuable thing in this project is what it declines to claim.

| Apparent finding | What the evidence actually says |
| --- | --- |
| Enterprise churns at **27.8%** against Mid-Market's **15.2%** | 95% intervals are [15.8%, 44.0%] and [8.2%, 26.5%] — they overlap. **Only 1 of 20 categories** across four breakdowns differs from the average |
| Discount matters — its coefficient grows when controlled | It does grow (+4.43 → +6.31), but **neither estimate is significant** (p = 0.068 and 0.158) |
| KMeans finds **two customer segments** | DBSCAN finds at most one cluster; **HDBSCAN calls 100% of customers noise** |

A less careful analysis would have published all three as results.

### 2. Behaviour predicts churn; size and revenue do not

Spearman correlation with the churn label, measured over a fixed two-month baseline window:

| Feature | Correlation | Reading |
| --- | --- | --- |
| Usage per seat | **−0.62** | The dominant signal. Disengagement, not size or sector |
| NPS | **−0.36** | Sentiment tracks behaviour closely |
| Discount | +0.15 | Heavily discounted deals are price-driven and leave on price |
| Ticket rate | +0.12 | Support load rises before departure |
| Mean seats | +0.04 | **Size does not predict churn** |
| Mean MRR | +0.02 | **Revenue does not predict churn either** |

**The two variables a revenue team reaches for first — how big the account is and how much it pays —
carry almost no signal.**

### 3. The model recovers the process that generated the data

Because the dataset is synthetic, the true coefficients are known. A logistic regression fitted on the
baseline window **agrees in sign with all seven of them** — usage, tickets, discount, NPS, segment,
industry risk and contract type. That is asserted as a test, so it fails loudly if a future change
removes the signal.

### 4. MRR cannot be predicted, and that is the first finding

**MRR is arithmetic, not a model.** It equals `seats × list price × (1 − discount)`, and every one of
those is a column. Regressing it on its own components scores **R² = 0.936** — impressive-looking and
meaningless, because the model is the invoice formula written out again. An analyst who cannot tell
*explaining* a quantity from *re-deriving* it will produce confident nonsense.

So the regression was re-aimed at something genuinely uncertain: **customer sentiment (NPS)**.

### 5. Only engagement explains sentiment, and seven extra features bought nothing

| Term | Effect on NPS | 95% CI | p | Significant? |
| --- | --- | --- | --- | --- |
| **usage_per_seat** | **+1.04** | **[+0.78, +1.31]** | **<0.0001** | **yes** |
| seats | +0.04 | [−0.00, +0.08] | 0.056 | no |
| industry_risk | +1.38 | [−5.33, +8.09] | 0.685 | no |
| support_tickets | +0.48 | [−3.20, +4.16] | 0.799 | no |
| discount_pct | −9.35 | [−51.09, +32.39] | 0.659 | no |

**The overall F-test is p ≈ 2e−09 while only 1 of 8 individual terms is significant.** Those are not in
conflict: the F-test asks *"does this group explain anything?"*; each t-test asks *"does this one add
anything, given the others are already in?"*

| Model | Terms | R² | Adjusted R² |
| --- | --- | --- | --- |
| Mean only | 0 | 0.000 | 0.000 |
| **usage_per_seat only** | **1** | 0.226 | **0.2215** |
| All features | 8 | 0.252 | 0.2206 |

Seven additional features **lowered** the adjusted R².

### 6. Out of sample, the simplest model won outright

Five-fold cross-validation, scored on customers the models never saw:

| Model | Mean R² | SD across folds |
| --- | --- | --- |
| **Linear regression, usage only** | **+0.204** | 0.051 |
| Ridge, all features | +0.139 | 0.095 |
| Gradient boosting, all features | +0.110 | 0.036 |
| Mean baseline | −0.028 | 0.033 |

A one-feature straight line beat both a regularised model and gradient boosting. With 200 rows and one
real driver, the extra capacity had nothing to learn and plenty to overfit.

Note the baseline scores **−0.028 rather than 0**: on unseen data, predicting the training mean is
slightly worse than nothing. That is what "R² = 0" means out of sample.

### 7. The churn threshold is a decision worth $53,700

**Accuracy is reported once, in order to be dismissed.** 80% of customers stay, so predicting "nobody
churns" is **80% accurate and identifies nobody**. ROC-AUC is the working metric:

| Model | ROC-AUC (5-fold) | SD |
| --- | --- | --- |
| Random forest | 0.962 | 0.024 |
| XGBoost | 0.955 | 0.040 |
| Logistic regression | 0.945 | 0.039 |
| *Majority class* | *0.500* | — |

**An honest caveat:** that AUC is high partly because this data was generated by a logistic process
using these very features, so a well-specified model recovers it almost exactly. On real customer data,
expect materially lower.

Every library defaults to 0.50, which treats a missed churner and a false alarm as equally bad. They
are not — **a missed churner is a lost account; a false alarm is one phone call.** Sweeping the
threshold on out-of-fold predictions:

| Threshold | Caught | Missed | False alarms | Expected cost |
| --- | --- | --- | --- | --- |
| **0.20** | **95%** | **2** | 30 | **lowest** |
| 0.50 *(default)* | 68% | 13 | 4 | **+$53,700** |
| 0.70 | 42% | 23 | 0 | |

The cost model ($5,000 lost account, $50 call) is an **assumption**, stated openly in the results file.

### 8. There are no natural customer segments

The honest question is not *"what are the clusters?"* but *"is there any cluster structure at all?"* —
because **KMeans always returns the number you ask for.**

| Method | Result |
| --- | --- |
| **KMeans, k=2** | silhouette **0.347** — *"weak, possibly artificial"* |
| **KMeans, k=3 to 6** | silhouette falls to 0.19–0.21 |
| **DBSCAN** (5 values of eps) | **at most 1 cluster** at every setting |
| **HDBSCAN** | **0 clusters — 100% of customers labelled noise** |

HDBSCAN putting *every* customer into noise is a strong statement: no dense island exists anywhere in
this feature space. The data is a **continuum**.

The two-group split that does emerge is **moderately stable** (Adjusted Rand Index 0.870 across ten
seeds) and separates small from large accounts — 42 seats and $2,066 MRR at 17% churn, against 220
seats and $22,760 at 33%. Useful for prioritisation, but **a continuum cut in half, not a discovery of
distinct customer types.**

The sharper result is in the projections (`reports/figures/20-projections.png`): colouring those same
customers by the segment we already had shows them **thoroughly intermixed in PCA, t-SNE and UMAP
alike.** The existing labels correspond to nothing in the data.

### 9. Two mistakes the pipeline caught in itself

Both are recorded in the code rather than quietly fixed:

- **`usage_events` did not scale with seats.** An early version drew total activity independent of
  account size, so a 5-seat account used the product as much as a 1,000-seat one (correlation −0.04).
  That made `usage_per_seat` — the strongest predictor in the design — a measure of how *few* seats a
  customer had. Fixed; the correlation with seats is now +0.88.
- **Fixing that broke two dependent variables.** Tickets and NPS still referenced *total* usage, which
  had just become a much larger number. Tickets flattened to a constant (churn correlation collapsed
  from +0.25 to +0.04) and NPS saturated at its ceiling with a skew of −8.9. Both now use the per-seat
  rate, and NPS sits at a skew of +0.04.

---

## The dashboard

`make serve` starts a five-tab Dash application at **http://127.0.0.1:8050**:

| Tab | What it shows |
| --- | --- |
| **Executive** | Eight KPIs — **accumulated revenue for the window**, latest MRR, annualised run-rate, change over the window, customers, churn rate, revenue concentration, and revenue sitting in high-risk accounts — then a chart of monthly revenue *and* the running total, plus the segment split |
| **Revenue** | A dropdown that re-slices revenue by segment, region or industry, showing both the total and the average per customer |
| **Churn risk** | A **threshold slider**. Moving it recounts the confusion matrix live and rewrites the call list, so the cost of the 0.50 default is visible rather than asserted |
| **Segments** | The clustering verdict, stated *above* the charts, then every customer plotted |
| **Data & models** | The eight-repair inventory, the invoice reconciliation, and every model's cross-validated scores |

**Demo:** drag the threshold from 0.50 to 0.20 and watch the expected cost fall from **$65,200 to
$11,500** — a **$53,700** saving, and the single most persuasive screen in the project.

The executive tab deliberately shows both **flow and stock**: revenue *per month* and the *accumulated*
total over the window. Those are different quantities — a rate and a sum — and a page showing only the
monthly movement gives no sense of how large the business is. The trend chart carries both at once:
bars for the month, a line for the running total, which flattens as churn eats into each month's
contribution.

### Why the dashboard imports almost nothing

`dashboard.py` imports **dash and plotly**. That is the entire list, and a test asserts it.

Three reasons, and all three matter:

1. **Deployment size.** The analysis stack — xgboost alone is about 200 MB — is close to 1 GB, against
   a runtime image that needs two packages. One stray import would bloat every build, with no symptom
   until deploy day. Hence the test.
2. **Speed.** Models are trained in `analysis.py`, never here. Moving a slider does arithmetic on 200
   stored numbers, so the response is instant. Retraining per interaction would be unusable.
3. **Honesty.** Every number was computed once, in one place, by code with tests. A dashboard free to
   recompute is a dashboard free to disagree with the report it is presenting.

Consequently `analysis.py` must run before `dashboard.py` — the dashboard has nothing to show until
`reports/results.json` exists, and it refuses to start with a message saying so rather than rendering
empty charts.

## How to run

```bash
make setup      # create venv-saas and install requirements
make all        # the whole pipeline in one command (main.py)
make test       # 40 tests
make serve      # start the dashboard at http://127.0.0.1:8050
```

`main.py` runs each step in its own process, so a failure names the step that failed rather than
producing one traceback. It also has flags: `--skip-generate`, `--skip-analyse`, `--serve`, `--help`.

`make analyse` takes about 45 seconds, most of it UMAP and the permutation-importance repeats.

### The environment is called `venv-saas`

A **virtual environment** is a private folder holding this project's packages, so installing `xgboost`
here cannot disturb another project on the same machine. It is named `venv-saas` rather than the usual
`.venv` so it is identifiable when several projects sit side by side.

`make setup` builds it. It is gitignored and should never be committed — hundreds of megabytes,
specific to one operating system, and fully reproducible from `requirements.txt`.

## Project layout

```
saas-revenue-analytics/
├── Dockerfile                   builds the deployed image: dash, plotly, 3 copied files
├── .dockerignore                keeps the virtualenv and generated data out of the build
├── deploy/huggingface/          Space front page + the deployment runbook
├── api/index.py                 Vercel entry point — kept, see Deployment
├── vercel.json                  Vercel routing — kept, see Deployment
├── requirements.txt             DEPLOYMENT deps (dash, plotly) — what the image installs
├── requirements-analysis.txt    ANALYSIS deps — what regenerates the data
├── config.py                    schema, constants, the true generating coefficients
├── data_gen.py                  builds the star schema, injects defects, loads SQLite
├── analysis.py                  clean → EDA → regression → classification → clustering
├── dashboard.py                 the Dash app — reads precomputed JSON only
├── main.py                      orchestration — runs the pipeline, optionally serves
├── tests/
│   ├── test_data_pipeline.py    16 tests: schema, leakage, signal
│   └── test_dashboard.py        24 tests: payload, deploy constraint, callbacks, entry point
├── data/README.md               provenance, the sampling rule, the defect inventory
├── data/raw/                    generated CSVs + SQLite (gitignored)
└── reports/
    ├── results.json             every number the dashboard reads
    ├── data_quality.json        what was wrong and what was done about it
    └── figures/                 22 PNGs
```

## Deployment — Hugging Face Spaces

The dashboard is packaged as a **Docker container**. `Dockerfile` at the repository root builds an
image that installs two libraries, copies three files, and serves the app with gunicorn on port 7860.

| File | What it does |
| --- | --- |
| `Dockerfile` | The whole deployment. Installs `dash` + `plotly`, copies `dashboard.py` and `reports/results.json`, runs gunicorn |
| `.dockerignore` | Keeps the virtualenv and the generated CSVs out of the build context. Docker does not read `.gitignore`, so without this a local build would ship hundreds of megabytes |
| `dashboard.py` | Exposes `server = app.server` — the Flask instance underneath Dash, and the object gunicorn imports as `dashboard:server` |
| `deploy/huggingface/space-README.md` | The Space's own front page. Hugging Face requires YAML at the very top of the Space's README, and that block would render as a stray table on this GitHub page — so the two are separate files |
| `deploy/huggingface/DEPLOY.md` | The step-by-step runbook |

The image stays small because the dashboard computes nothing. It reads one precomputed JSON file, so
the container never needs pandas, scikit-learn or XGBoost — **roughly 300 MB instead of ~1 GB**, and it
starts in about two seconds.

### The dependency split, and why it exists

The files are split by *what they are for*:

- **`requirements.txt`** — what the dashboard needs to **run**. Two packages.
- **`requirements-analysis.txt`** — what you additionally need to **regenerate the data**. It starts
  with `-r requirements.txt`, so installing it gives you both.

`make setup` installs the analysis file, so a local clone is complete by default.

### Three decisions that made deployment possible

1. **The dashboard rebuilds its charts in Plotly** rather than displaying the PNG figures. Those are
   committed for this README, but a container reading them would need the whole image set and would be
   less useful than a chart you can filter.
2. **No model runs at request time.** `analysis.py` writes `reports/results.json`; the dashboard reads
   it. That is why moving a slider is instant instead of triggering a refit.
3. **pandas was removed from the dashboard entirely.** It was used in four places — filtering a list,
   summing a column, taking a set of ids — all of which plain Python does. Dropping it also dropped
   NumPy, taking the single largest dependency out of the runtime image.

### Verified locally, before deploying

The exact command in the Dockerfile's `CMD` was run against the real application:

- `gunicorn --bind 0.0.0.0:7860 --workers 2 --threads 4 dashboard:server` binds and boots both workers.
- `/` returns **200**; `/_dash-layout` returns **200** carrying all five tab labels; `/_dash-dependencies`
  returns **200** listing **6 callbacks**, including the churn-threshold slider.
- Checking those two endpoints matters because a deployment that serves the page but not them renders
  blank — which looks like a styling problem rather than a routing one.
- `--no-control-socket` is load-bearing, not cosmetic. gunicorn 26 opens a control socket at
  `/run/user/1000/gunicorn.ctl` by default, which does not exist in a container, so it logs
  `Control server error: [Errno 30] Read-only file system` on every start. The flag removes it; with the
  flag the log is clean.

**What is not verified:** the image itself has never been built. Docker was not available on the machine
where this was written, so the `Dockerfile` is correct against Hugging Face's documented requirements —
user ID 1000, `WORKDIR` before `COPY`, `--chown=user` — but the first build is the real test.

### Two hosts that did not work, and why

Recorded because the reasons are more useful than the outcome:

- **Vercel** — `api/index.py` and `vercel.json` are that attempt's leftover configuration. Technically
  viable at ~74 MB against a 500 MB limit, but deployment was blocked at account verification. Kept
  because the path is not closed.
- **Netlify** — cannot host this at all. Netlify Functions run JavaScript and TypeScript only; the
  Python support Netlify documents is for *build* steps, not for serving an application.

Hugging Face Spaces was chosen because it accepts an arbitrary Dockerfile, so no bundle ceiling applies.

## Architecture: why the dashboard is separate

**`dashboard.py` imports only `dash` and `plotly`** — plus the standard library. No pandas, no NumPy.
Every model runs in `analysis.py` and writes small JSON artefacts to `reports/`; the dashboard reads
those and renders.

This is not tidiness. The analysis stack — xgboost alone is roughly 200 MB, scikit-learn and SciPy
about 120 MB each — is close to 1 GB, and a deployed image carrying it would be slow to build and slow
to start for no benefit, because not one line of it runs in the browser.

Separating them is better practice anyway: models should not retrain on every page load.

## Code style: commentary

Every file is written to be readable by someone with basic Python experience — a header explaining what
the file does and why, section banners before each block, and an inline comment on any line whose
*intent* is not obvious. Every function has a docstring.

The commentary explains **why a line exists and what would break without it**, not what the syntax
does. `# loop over rows` adds nothing; `# iterrows() upcasts every column to one dtype, which is why
this uses itertuples()` records a bug that was actually hit.

## Limitations

Stated up front, because synthetic data has limits that should not be discovered later:

- **The generating coefficients are assumptions, not findings.** The industry risk index encodes a
  belief that some verticals churn more. It is not evidence about real markets.
- **The dataset is small by design** (200 customers). Enough to demonstrate method; not enough to
  support narrow claims. A 20% churn rate on 200 customers is 40 events.
- **No seasonality, no macro effects, no competitive dynamics.** Four consecutive months cannot show a
  seasonal pattern, and nothing here reacts to the outside world.
- **Billing is cleaner than reality.** MRR comes from a formula with 3% noise plus eight deliberate
  defects. Real billing data is far messier.
- **The high churn AUC is partly an artefact** of the data being generated by a logistic process using
  the same features the model sees.

## Appendix: where the libraries came from

The brief was to use as much of the IBM Data Science certification's library set as possible. An honest
accounting rather than a claim.

**Used and present in the certification corpus:** `pandas`, `numpy`, `scipy`, `matplotlib`, `seaborn`,
`plotly`, `scikit-learn` (including `linear_model`, `ensemble`, `tree`, `cluster`, `decomposition`,
`manifold`, `preprocessing`, `impute`, `compose`, `pipeline`, `model_selection`, `metrics`,
`inspection`, `utils.class_weight`); `sqlite3`, `csv`, `json`, `os`, `sys`, `time`, `math`, `datetime`,
`warnings`, `unicodedata`, `zipfile`, `io`, `re`, `random`; `pywaffle`, `wordcloud`, `prettytable`,
`openpyxl`, `jinja2`, `tqdm`, `Pillow`.

**Deliberate extensions, each for a stated reason:**

| Library | Why it was added |
| --- | --- |
| `statsmodels` | Named in the course notes but never imported in any artefact. Needed for coefficient inference — scikit-learn does not produce p-values or confidence intervals |
| `xgboost` — `XGBClassifier` | The corpus imports `XGBRegressor` only. The classifier is used for churn because gradient boosting is the most-requested tabular method in current postings |
| `GradientBoostingRegressor` | The corpus imports `RandomForestRegressor`. Used in step 3 for a boosted comparison |

**Not used, and why:** `requests` and `bs4` need live internet and this dataset is synthetic;
`yfinance` and `nba_api` need live APIs; `ibm_watsonx_ai` and the two `langchain` packages need IBM
Cloud credentials; `IPython.display`, `ipywidgets` and the `%sql` magic need a notebook kernel rather
than a script; `geopandas`, `contextily` and `shapely` add three heavy dependencies for a map this
scenario does not need; `pyodide`, `js` and `micropip` are browser-runtime only.
