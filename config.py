"""
config.py — single source of truth for the SaaS revenue analytics project.

WHY THIS FILE EXISTS
--------------------
Every number that shapes the data, the analysis or the dashboard is declared
here, once. Nothing downstream hard-codes a row count, a price or a file path.

That matters more than usual in this project for one specific reason: the data
is synthetic, so WE define the process that generates it. If those parameters
were scattered across three files, we could never answer the only question that
makes synthetic data interesting -- "did the model recover the process that
actually produced the data?"

So the generating coefficients live here, in the open, and the analysis checks
the fitted model against them.

THE BUSINESS SCENARIO
---------------------
A fictional B2B SaaS company, "Northwind Analytics", sells seat-based
subscriptions to businesses. We observe 200 customers over 4 months of 2026.
Some customers stop subscribing. The questions the project answers are:

  1. What does the revenue base actually look like?          (EDA)
  2. What drives monthly recurring revenue?                  (regression)
  3. Which customers are about to churn?                     (classification)
  4. Are there natural customer segments?                    (clustering)

Every file produced stays at or below 800 rows.
"""

# --- Imports ---------------------------------------------------------------
# This file deliberately imports almost nothing. It is a SETTINGS file: it
# declares data and constants, and does no computation, so it needs no maths or
# plotting libraries. Keeping it dependency-free is what lets every other file
# import it without pulling in the whole analysis stack.
#
# os is the one exception, and only because paths have to be built and folders
# have to exist before anything can be written to them.
import os
# ---------------------------------------------------------------------------
# 1. Paths
# ---------------------------------------------------------------------------
# ? The corpus uses `os` rather than `pathlib`, so this file does too -- the
# ? brief was to stay as close to the certification's own libraries as
# ? possible. os.path.join is the portable way to build paths with `os`.

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
FIGURES_DIR = os.path.join(REPORTS_DIR, "figures")

# * The star schema is written out in two forms on purpose:
# *   - CSV, so the data is inspectable by eye and openable in Excel
# *   - SQLite, so analysis.py can demonstrate real joins and aggregation
# * Writing both is slightly redundant and entirely deliberate: the SQL section
# * of the analysis depends on the database file existing.
SQLITE_PATH = os.path.join(DATA_RAW_DIR, "saas_revenue.db")

# * Precomputed analysis results. dashboard.py reads ONLY these files.
# ! This separation is not tidiness, it is a hard deployment constraint.
# ! The deployed image installs two libraries; the analysis stack
# ! (scikit-learn + xgboost + scipy + matplotlib) is roughly 1 GB and would
# ! slow every build to serve code that never runs in a browser. So the
# ! dashboard must never import it — it reads these JSON artefacts instead.
RESULTS_PATH = os.path.join(REPORTS_DIR, "results.json")

# ---------------------------------------------------------------------------
# 2. Reproducibility
# ---------------------------------------------------------------------------
# * One seed controls everything random. Re-running data_gen.py must produce a
# * byte-identical dataset, or the analysis results cannot be trusted between
# * runs and no one else can reproduce the figures.
RANDOM_SEED = 42

# ---------------------------------------------------------------------------
# 3. Shape of the data
# ---------------------------------------------------------------------------
# * 200 customers x 4 months would be 800 rows if nobody churned. They do
# * churn, and a churned customer stops appearing -- so the fact table lands
# * slightly under the cap. That is realistic (a cancelled subscription has no
# * billing rows) and it keeps every file within the 800-row limit.
N_CUSTOMERS = 200
N_MONTHS = 4
MONTHS = [202601, 202602, 202603, 202604]      # date_key values, YYYYMM

# * Target churn rate over the window. 20% of 200 customers = about 40
# * churners, which is enough to fit a classifier without the metrics becoming
# * unstable. Below roughly 25 positives, ROC-AUC moves several points on a
# * different random seed and the results stop meaning anything.
TARGET_CHURN_RATE = 0.20

N_REPS = 8
N_REGIONS = 6
N_PLANS = 6

# ---------------------------------------------------------------------------
# 4. The dimension tables
# ---------------------------------------------------------------------------
# Regions — one row per sales territory.
#
#   region_id    unique key; other tables point at this number
#   region_name  the label a human reads on the dashboard
#   country      the country the region is anchored in
#   timezone     an IANA timezone name, e.g. "America/Mexico_City".
#                Stored rather than assumed, because a support team needs to
#                know what "business hours" means for each territory.
#   currency     the currency deals in that region are written in. This is the
#                column that makes a real FX discussion possible later.
REGIONS = [
    {"region_id": 1, "region_name": "North America",  "country": "United States", "timezone": "America/Chicago",   "currency": "USD"},
    {"region_id": 2, "region_name": "Mexico",         "country": "Mexico",        "timezone": "America/Mexico_City", "currency": "MXN"},
    {"region_id": 3, "region_name": "LATAM",          "country": "Brazil",        "timezone": "America/Sao_Paulo", "currency": "BRL"},
    {"region_id": 4, "region_name": "EMEA",           "country": "Germany",       "timezone": "Europe/Berlin",     "currency": "EUR"},
    {"region_id": 5, "region_name": "UK & Ireland",   "country": "United Kingdom","timezone": "Europe/London",     "currency": "GBP"},
    {"region_id": 6, "region_name": "APAC",           "country": "Singapore",     "timezone": "Asia/Singapore",    "currency": "USD"},
]

# Plans — the subscription catalogue.
#
#   plan_id               unique key
#   plan_name             the label customers see
#   list_price_per_seat   the UNDISCOUNTED price, per seat, per month.
#                         Discounts are applied later on the fact table, so
#                         this stays the clean "list" figure.
#   tier_rank             1 = cheapest, 6 = most expensive. An ORDERED
#                         category: the model can use "is this a higher tier?"
#                         which a bare name could not answer.
#   seat_band_min/max     the seat range normally sold on this plan. The
#                         generator draws seat counts from inside this band.
#
# Adjacent bands OVERLAP on purpose (Team 10-45 vs Growth 20-90, and so on).
# Real catalogues overlap, and tidy non-overlapping bands would make the
# clustering exercise trivial — every cluster would simply be one plan.
#
# The bands are also NARROWER than a first draft used. An earlier version ran
# to 1,200 seats on the top plan, which produced single invoices above $200,000
# and an implied ARR of $42 million from 200 customers — a plausible enterprise
# figure that was wildly implausible for the fictional company being described.
# It also produced a revenue distribution with a skew above +3, where a handful
# of accounts dominated every average. These numbers describe roughly a $3M ARR
# business, which is what "200 customers" should mean.
PLANS = [
    {"plan_id": 1, "plan_name": "Starter",     "list_price_per_seat": 15.0,  "tier_rank": 1, "seat_band_min": 5,   "seat_band_max": 20},
    {"plan_id": 2, "plan_name": "Team",        "list_price_per_seat": 29.0,  "tier_rank": 2, "seat_band_min": 10,  "seat_band_max": 45},
    {"plan_id": 3, "plan_name": "Growth",      "list_price_per_seat": 49.0,  "tier_rank": 3, "seat_band_min": 20,  "seat_band_max": 90},
    {"plan_id": 4, "plan_name": "Business",    "list_price_per_seat": 79.0,  "tier_rank": 4, "seat_band_min": 50,  "seat_band_max": 180},
    {"plan_id": 5, "plan_name": "Enterprise",  "list_price_per_seat": 119.0, "tier_rank": 5, "seat_band_min": 120, "seat_band_max": 320},
    {"plan_id": 6, "plan_name": "Enterprise+", "list_price_per_seat": 169.0, "tier_rank": 6, "seat_band_min": 250, "seat_band_max": 500},
]

# Sales reps — who owns which account.
#
#   rep_id     unique key
#   rep_name   the label shown on the dashboard
#   team       SMB / Mid-Market / Enterprise. Accounts are usually assigned to
#              the team that matches their size, though not always.
#   hire_date  the date the rep started. This exists for ONE reason: a rep
#              cannot own a customer who signed up before the rep was hired.
#              That impossibility is a data-quality check, and one of the
#              eight deliberate defects breaks it on purpose.
REPS = [
    {"rep_id": 1, "rep_name": "Ana Ruiz",        "team": "Enterprise", "hire_date": "2019-03-11"},
    {"rep_id": 2, "rep_name": "Marcus Bell",     "team": "Enterprise", "hire_date": "2020-07-01"},
    {"rep_id": 3, "rep_name": "Priya Nair",      "team": "Mid-Market", "hire_date": "2021-01-18"},
    {"rep_id": 4, "rep_name": "Tom Okafor",      "team": "Mid-Market", "hire_date": "2021-09-06"},
    {"rep_id": 5, "rep_name": "Sofia Marchetti", "team": "Mid-Market", "hire_date": "2022-04-25"},
    {"rep_id": 6, "rep_name": "Daniel Kim",      "team": "SMB",        "hire_date": "2023-02-13"},
    {"rep_id": 7, "rep_name": "Lucia Fernandez", "team": "SMB",        "hire_date": "2023-08-21"},
    # * Omar was hired MID-WINDOW (June 2025) on purpose. Customers who signed
    # * before that date cannot have been his accounts, and one of the eight
    # * deliberate defects assigns four of them to him to create exactly that
    # * impossibility. Without a mid-window hire date the defect cannot exist --
    # * an earlier version had every rep hired before every customer, so the
    # * "impossible" assignment was in fact perfectly legal.
    {"rep_id": 8, "rep_name": "Omar Haddad",     "team": "SMB",        "hire_date": "2025-06-15"},
]

SEGMENTS = ["SMB", "Mid-Market", "Enterprise"]
CHANNELS = ["Inbound", "Outbound", "Partner", "Self-serve", "Expansion"]

# Industries — the customer's sector, with a churn risk index.
#
#   industry          the label, joined onto each customer
#   churn_risk_index  a number added into the churn calculation. NEGATIVE
#                     means the vertical retains well (Software at -0.35),
#                     POSITIVE means it churns more (Hospitality at +0.70).
#
# ! READ THIS AS AN ASSUMPTION, NOT A FINDING.
# ! These numbers encode a belief that some sectors churn more than others.
# ! They are invented for this synthetic dataset. They are NOT evidence about
# ! any real market, and they must never be quoted as if they were.
INDUSTRIES = [
    {"industry": "Software",            "churn_risk_index": -0.35},
    {"industry": "Financial Services",  "churn_risk_index": -0.20},
    {"industry": "Manufacturing",       "churn_risk_index":  0.15},
    {"industry": "Retail",              "churn_risk_index":  0.45},
    {"industry": "Hospitality",         "churn_risk_index":  0.70},
    {"industry": "Media",               "churn_risk_index":  0.30},
    {"industry": "Healthcare",          "churn_risk_index": -0.10},
    {"industry": "Logistics",           "churn_risk_index":  0.25},
]

# Support ticket topics — the short label attached to each customer-month.
#
# WHY THIS EXISTS: one of the certification's libraries is `wordcloud`, which
# needs TEXT. A count of tickets and five fixed churn reasons are not text. So
# each customer-month records the topic that dominated its support requests,
# which gives the word cloud something real to draw.
#
#   topic    a short, human-readable label
#   weight   the baseline share BEFORE it is adjusted for the customer's state
#            (see build_monthly_panel: a month with more tickets leans toward
#            the failure topics; a month with low usage leans toward the
#            usability topics). That adjustment matters — it means the cloud
#            shows something about the customer rather than pure randomness.
#
# ! These labels are invented for the synthetic dataset. They are plausible for
# ! a B2B SaaS product; they are not observations about any real one.
TICKET_TOPICS = [
    {"topic": "Login and SSO failure",      "weight": 0.14, "kind": "failure"},
    {"topic": "Data sync error",            "weight": 0.13, "kind": "failure"},
    {"topic": "Report export failed",       "weight": 0.12, "kind": "usability"},
    {"topic": "Slow dashboard loading",     "weight": 0.12, "kind": "usability"},
    {"topic": "API rate limit reached",     "weight": 0.09, "kind": "failure"},
    {"topic": "Permission and access issue","weight": 0.09, "kind": "usability"},
    {"topic": "Billing discrepancy",        "weight": 0.08, "kind": "commercial"},
    {"topic": "User provisioning request",  "weight": 0.08, "kind": "onboarding"},
    {"topic": "Integration setup help",     "weight": 0.08, "kind": "onboarding"},
    {"topic": "Feature request",            "weight": 0.07, "kind": "commercial"},
]

# Churn reasons — why a customer left, when they did.
#
#   churn_reason_id  unique key
#   churn_reason     the label
#
# ! POST-HOC INFORMATION. A reason is only known AFTER someone has left.
# ! It therefore lives on dim_customer, never on the monthly fact table, and it
# ! must NEVER be used as a model feature. Using it would be like predicting
# ! today's weather from tomorrow's newspaper: the answer would look perfect
# ! and mean nothing. This is called target leakage — see LEAKAGE_WARNING below.
CHURN_REASONS = [
    {"churn_reason_id": 1, "churn_reason": "Price / budget cut"},
    {"churn_reason_id": 2, "churn_reason": "Switched to competitor"},
    {"churn_reason_id": 3, "churn_reason": "Product gap"},
    {"churn_reason_id": 4, "churn_reason": "Low adoption"},
    {"churn_reason_id": 5, "churn_reason": "Company closed / M&A"},
]

# ---------------------------------------------------------------------------
# 5. THE TRUE GENERATING PROCESS  --  the heart of this file
# ---------------------------------------------------------------------------
# ! These are the coefficients that ACTUALLY produce churn in data_gen.py.
# !
# ! We record them because they let the analysis do something a real dataset
# ! cannot: check whether the fitted model recovered the process that generated
# ! the data. If the logistic regression says support_tickets matters and the
# ! truth below also says it matters, the pipeline is working. If they disagree,
# ! something is wrong with the features, the split or the encoding -- and we
# ! can prove it rather than guess.
# !
# ! This is the single strongest interview point in the project. Use it.

TRUE_CHURN_INTERCEPT = -1.15

TRUE_CHURN_COEFFICIENTS = {
    # * Churn goes UP with these.
    "support_tickets":      0.28,   # more tickets -> more frustration
    "discount_pct":         2.10,   # deeply discounted -> bought on price, leaves on price
    "is_smb":               0.55,   # smaller customers churn more
    "industry_risk":        0.85,   # vertical effect, from INDUSTRIES above
    "months_active":        0.12,   # mild mid-contract risk bump
    # * Churn goes DOWN with these.
    "usage_per_seat":      -0.85,   # the strongest protective factor
    "nps_score":           -0.045,  # sentiment, self-reported
    "is_annual_contract":  -0.70,   # commitment locks customers in
}

# * Noise is added on the log-odds scale before the sigmoid. Without it every
# * customer with identical features would churn identically, the model would
# * score a suspicious 1.00 ROC-AUC, and the project would prove nothing.
CHURN_NOISE_SD = 0.55

# MRR is generated as seats x list price x (1 - discount), then given a
# small multiplicative wobble for realism. The formula is deterministic
# enough that analysis.py can verify the invoice arithmetic exactly.
MRR_NOISE_SD = 0.03

# ---------------------------------------------------------------------------
# 6. Deliberate defects
# ---------------------------------------------------------------------------
# * The brief asked for LIGHT messiness: enough that cleaning and imputation
# * have something real to act on, not so much that the analysis is swamped.
# * Every injected defect is recorded in reports/data_quality.json so the
# * dashboard can show what was wrong and what was done about it.
DEFECT_CUSTOMER_MISSING_INDUSTRY = 6     # blank industry cells
DEFECT_CUSTOMER_BLANK_REGION = 3         # blank region_id, breaks a foreign key
DEFECT_FACT_MISSING_USAGE = 18           # blank usage_events -> needs imputing
DEFECT_FACT_NEGATIVE_USAGE = 4           # impossible negative usage
DEFECT_DUPLICATE_FACT_ROWS = 12          # one duplicated block of 12 rows
DEFECT_DISCOUNT_OUT_OF_RANGE = 5         # discount > 1.0, impossible
DEFECT_MIXED_DATE_FORMAT = 8             # signup_date in DD/MM/YYYY not ISO

# ---------------------------------------------------------------------------
# 7. Analysis parameters
# ---------------------------------------------------------------------------
# ? The split is declared BEFORE any model is fitted, and it is stratified
# ? because churn is imbalanced (about 20%). A plain random split can hand the
# ? training set 14% churners and the test set 26%, which makes every metric
# ? noisy for no reason.
TEST_SIZE = 0.25
STRATIFY_ON = "is_churned"

# * Cross-validation folds for the tuning searches. Five folds on 150 training
# * rows means 30 rows per fold -- the practical floor before scores swing on
# * individual customers.
CV_FOLDS = 5

# * The churn threshold. 0.5 is the default and usually the wrong choice: for
# * a retention team, missing a churner costs more than a false alarm. The
# * analysis sweeps this and the dashboard lets the user move it.
DECISION_THRESHOLD = 0.50

# Clustering. k is searched 2..6 and the final choice is justified by
# silhouette and Davies-Bouldin rather than asserted.
CLUSTER_K_RANGE = range(2, 7)
CLUSTER_KMEANS_N_INIT = 10

# ---------------------------------------------------------------------------
# 8. Presentation
# ---------------------------------------------------------------------------
# * One house style for every figure, so the report and the dashboard match.
FIGURE_DPI = 150
FIGURE_SIZE = (11, 6)
PALETTE = ["#2E5EAA", "#E4572E", "#17B890", "#F4A259", "#7B6D8D", "#4C9F70"]
BRAND_PRIMARY = "#2E5EAA"
BRAND_ACCENT = "#E4572E"


# ---------------------------------------------------------------------------
# 9. Schema definition
# ---------------------------------------------------------------------------
# * The schema is data, not documentation. analysis.py reads it to decide which
# * columns are numeric, tests use it to assert the database matches, and
# * data_gen.py uses it to keep column order stable across CSV and SQLite.
# * A schema written once and read by three consumers cannot drift.

SCHEMA = {
    "dim_region": {
        "primary_key": "region_id",
        "columns": ["region_id", "region_name", "country", "timezone", "currency"],
    },
    "dim_plan": {
        "primary_key": "plan_id",
        "columns": ["plan_id", "plan_name", "list_price_per_seat", "tier_rank",
                    "seat_band_min", "seat_band_max"],
    },
    "dim_rep": {
        "primary_key": "rep_id",
        "columns": ["rep_id", "rep_name", "team", "hire_date"],
    },
    "dim_date": {
        "primary_key": "date_key",
        "columns": ["date_key", "month_name", "month_num", "quarter", "year", "is_quarter_end"],
    },
    "dim_customer": {
        "primary_key": "customer_id",
        "columns": ["customer_id", "company_name", "industry", "region_id", "segment",
                    "acquisition_channel", "signup_date", "rep_id", "is_annual_contract",
                    "churned_month", "churn_reason_id", "months_active"],
        "foreign_keys": {"region_id": "dim_region", "rep_id": "dim_rep"},
    },
    "fact_subscription_monthly": {
        "primary_key": "fact_id",
        "columns": ["fact_id", "customer_id", "plan_id", "date_key", "seats", "mrr",
                    "usage_events", "support_tickets", "discount_pct", "nps_score",
                    "primary_ticket_topic"],
        "foreign_keys": {"customer_id": "dim_customer", "plan_id": "dim_plan",
                         "date_key": "dim_date"},
    },
}

# * Written to SQLite in this order so foreign-key targets exist before the
# * tables that reference them. Getting this order wrong is the most common
# * cause of a foreign-key failure on load.
TABLE_LOAD_ORDER = [
    "dim_region", "dim_plan", "dim_rep", "dim_date",
    "dim_customer", "fact_subscription_monthly",
]

# ! Churn is DERIVED from the panel, never stored on the fact table.
# !
# ! If a boolean `is_churned` sat on a monthly fact row, then a row in month 1
# ! would already "know" the customer leaves in month 3. Any model trained on
# ! it would score close to perfect and mean nothing. This is target leakage,
# ! it is the most common way a portfolio project is quietly wrong, and the
# ! column simply does not exist here.
# !
# ! Churn is computed in analysis.py as: a customer's last observed month is
# ! earlier than the final month in the panel.
LEAKAGE_WARNING = (
    "Churn is derived from the panel (last observed month < final month). "
    "It is never a column on fact_subscription_monthly. "
    "churn_reason_id is post-hoc and must never be used as a feature."
)


def ensure_directories():
    """Create the output folders if they do not exist. Idempotent."""
    for path in (DATA_RAW_DIR, REPORTS_DIR, FIGURES_DIR):
        os.makedirs(path, exist_ok=True)


if __name__ == "__main__":
    # * Running this file directly is a quick self-check, not a pipeline step.
    # * It prints the configuration so a reader can confirm what will be built
    # * before generating a single row.
    ensure_directories()
    print("CONFIG — what this module defines")
    print()
    print("  scenario         Northwind Analytics, B2B seat-based SaaS")
    print("  customers        " + str(N_CUSTOMERS))
    print("  months           " + str(N_MONTHS) + "  " + str(MONTHS))
    print("  target churn     " + str(int(TARGET_CHURN_RATE * 100)) + " %  (~"
          + str(int(N_CUSTOMERS * TARGET_CHURN_RATE)) + " churners)")
    print()
    print("  tables           " + str(len(SCHEMA)) + "  (4 dimensions + 1 fact + dim_date)")
    for name, spec in SCHEMA.items():
        print("                   " + name.ljust(28) + str(len(spec["columns"])) + " columns")
    print()
    print("  split            " + str(int((1 - TEST_SIZE) * 100)) + " / "
          + str(int(TEST_SIZE * 100)) + " stratified on " + STRATIFY_ON)
    print("  cv folds         " + str(CV_FOLDS))
    print()
    print("  true coefficients are recorded in TRUE_CHURN_COEFFICIENTS")
    print("                   so the fitted model can be checked against the")
    print("                   process that actually generated the data")
    print()
    print("  outputs          " + os.path.join("data", "raw") + "/  (CSV + SQLite)")
    print("                   " + os.path.join("reports") + "/     (JSON the dashboard reads)")
