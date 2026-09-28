# Data provenance — the synthetic star schema

**Nothing in this folder is committed to Git.** Every file here is produced by `python data_gen.py`
and is reproducible from a single seed. A stored copy would add 50 KB of churn to every commit and
prove nothing; the *generator* is the artefact, and the CSVs are its by-product.

## How the data is made

```
config.py ──▶ data_gen.py ──▶ data/raw/*.csv, *.db, *.zip
   │              │                    └──▶ reports/data_quality.json
   │              └── the eight deliberate defects are injected here
   └── the schema, the constants, and the TRUE churn coefficients
```

Run `make generate`. It takes about a second. The output is identical every time, because
`config.RANDOM_SEED` seeds both Python's `random` module and NumPy's random generator.

## The six tables

A **star schema**: one central fact table surrounded by dimensions. The name comes from the shape —
the fact table sits in the middle and the dimensions point at it like the points of a star.

| Table | Rows | What one row is | Key |
| --- | --- | --- | --- |
| `fact_subscription_monthly` | 754 | one customer, in one month | `fact_id` |
| `dim_customer` | 200 | one customer | `customer_id` |
| `dim_rep` | 8 | one sales rep | `rep_id` |
| `dim_region` | 6 | one sales territory | `region_id` |
| `dim_plan` | 6 | one subscription tier | `plan_id` |
| `dim_date` | 4 | one month in the window | `date_key` |

A **fact** table holds things that happen — measurements, one row per event. A **dimension** holds
things that *are* — the descriptive context you filter and group by. Splitting them this way is what
makes SQL joins meaningful instead of decorative.

The fact table has 754 rows rather than 800 because a customer who churns **stops having rows**.
That is not a defect; it is what a cancelled subscription looks like.

## Why 754 and not 800

200 customers × 4 months would be exactly 800. But 40 customers (20%) churn, and a churned customer's
subscription ends — so they have 2 or 3 months of history instead of 4. That is the panel structure,
and the churn label is derived from it.

## The eight deliberate defects

Injected on purpose, and listed in `reports/data_quality.json` with their size and what each one
breaks. They are light enough that the analysis is not swamped, and specific enough that cleaning and
imputation have real work to do.

| Defect | Rows | What it breaks |
| --- | --- | --- |
| Blank `industry` | 6 | Cannot group by industry until imputed |
| Blank `region_id` | 3 | **A broken foreign key** — an inner join silently drops these customers |
| Mixed date formats | 8 | `pd.to_datetime` parses inconsistently |
| Blank `usage_events` | 18 | Biases any mean computed by dropping rows |
| Negative `usage_events` | 4 | Impossible values drag averages down |
| Discount above 100% | 5 | Produces negative MRR |
| Duplicated fact rows | 12 | Double-counts revenue and inflates usage |
| Rep hired after signup | 4 | Temporal impossibility |

## The rule that governs all of it

**Churn is never a stored column.** A boolean `is_churned` on a January fact row would mean that row
already "knew" the customer left in March. Any model trained on it would score close to perfect and
prove nothing. This is **target leakage**, it is the most common way a portfolio project is quietly
wrong, and a test in `tests/` asserts the column does not exist.

Churn is derived instead: *a customer whose last observed month precedes the final month has left.*

`churn_reason_id` is likewise recorded **after** someone leaves, so it lives on `dim_customer` and is
never a feature.

## Why the data is synthetic, and what that costs

The features **genuinely cause churn** here: usage, tickets, discount and sentiment are generated
first, and churn is then derived from them by a logistic process. The tempting shortcut — decide who
leaves, then generate that customer's usage to "look churny" — produces circular data where the
features are drawn *from* the label.

Because causality runs the right way, the analysis can honestly ask whether the fitted model
**recovered the process that generated the data**. That is something a real dataset cannot offer.

**The honest cost:** the generating coefficients are assumptions, not findings. The industry risk
index in particular encodes a belief that some sectors churn more. Nothing here is evidence about any
real market, and no number from this dataset should be quoted as if it were.
