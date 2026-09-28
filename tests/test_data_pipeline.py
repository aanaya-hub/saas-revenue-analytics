"""
test_data_pipeline.py — tests for the synthetic data and the analysis contract.

Run with:  python -m pytest -q

WHY THESE TESTS AND NOT OTHERS
------------------------------
Three kinds of test, in descending order of how much they protect:

1. SCHEMA tests. Every foreign key resolves, row counts stay inside the 800-row
   cap, and integer keys are actually integers. The first version of data_gen.py
   shipped every fact column as float64 -- keys included -- because a loop used
   `iterrows()`. The joins still worked, so nothing looked wrong. A test is the
   only thing that catches that class of bug.

2. LEAKAGE tests. These assert that information which would not exist at
   prediction time is absent from the feature set. Leakage is the mistake that
   makes a model look excellent and be worthless, and it is invisible in the
   output -- only in the design. So it gets asserted.

3. SIGNAL tests. The data is synthetic, so the generating process is known.
   These check that a model can actually recover it. If the signal ever
   disappears, every modelling result downstream becomes meaningless, and it is
   far better to fail here than to publish a dashboard of noise.
"""

# --- Standard library -----------------------------------------------------
import json          # reads reports/data_quality.json to check it is complete
import os            # builds the file paths to the generated CSVs
import sqlite3       # opens the .db file to confirm it matches the CSVs
import sys           # edits the import path so `import config` works below

# --- Third-party ----------------------------------------------------------
import numpy as np   # np.sign() and array maths in the coefficient tests
import pandas as pd  # loads the CSVs into DataFrames to assert things about them
import pytest        # the test framework: @pytest.fixture and pytest.skip

# ? WHY THIS LINE EXISTS
# ? When pytest runs this file, Python's import path does NOT include the
# ? project root by default — only the tests/ folder. Without this line,
# ? `import config` on the next line would fail with ModuleNotFoundError.
# ?
# ? __file__ is this test file. os.path.dirname() strips the filename, giving
# ? tests/. A second dirname() goes up one more level to the project root.
# ? insert(0, ...) puts that root at the FRONT of the search path, so config.py
# ? is found there and not shadowed by anything else.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

DATA_DIR = config.DATA_RAW_DIR

# * Columns that must never appear in a feature set, with the reason. This is
# * the leakage contract, written as data so a test can enforce it.
FORBIDDEN_FEATURES = {
    "churned_month": "the label itself",
    "churn_reason_id": "recorded AFTER the customer left",
    "months_active": "a churner has fewer months BY CONSTRUCTION",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tables():
    """Load the generated CSVs once for the whole module."""
    missing = [
        os.path.join(DATA_DIR, f"{name}.csv")
        for name in config.TABLE_LOAD_ORDER
        if not os.path.exists(os.path.join(DATA_DIR, f"{name}.csv"))
    ]
    if missing:
        pytest.skip(
            "Generated data not present. Run `python data_gen.py` first. "
            f"Missing: {missing}"
        )
    return {
        name: pd.read_csv(os.path.join(DATA_DIR, f"{name}.csv"))
        for name in config.TABLE_LOAD_ORDER
    }


# ---------------------------------------------------------------------------
# 1. Schema and shape
# ---------------------------------------------------------------------------

def test_every_table_is_within_the_row_cap(tables):
    """No file may exceed 800 rows. This is the project brief's hard constraint."""
    for name, df in tables.items():
        assert len(df) <= 800, f"{name} has {len(df)} rows, over the 800 cap"


def test_primary_keys_are_unique(tables):
    """A duplicated primary key means the dimension is ambiguous."""
    for name, spec in config.SCHEMA.items():
        pk = spec["primary_key"]
        df = tables[name]
        if name == "fact_subscription_monthly":
            # * The duplicate-rows defect is injected on purpose, so the raw
            # * fact table is expected to fail this. The analysis must dedupe.
            continue
        assert df[pk].is_unique, f"{name}.{pk} is not unique"


def test_dual_use_tables_are_declared_with_their_reasons():
    """The leakage contract must name every forbidden column and say why."""
    for column, reason in FORBIDDEN_FEATURES.items():
        assert reason, f"{column} is forbidden but no reason is recorded"


def test_integer_keys_are_integers_not_floats(tables):
    """Keys must not be stored as floats.

    The bug this guards against: building a DataFrame from `iterrows()` upcasts
    every column to a common dtype, turning 202601 into 202601.0. SQLite then
    declares the column REAL. The joins still work because SQLite compares
    numerically, so the defect is invisible until someone reads the CSV.
    """
    for name, columns in [
        ("fact_subscription_monthly", ["fact_id", "customer_id", "plan_id", "date_key", "seats"]),
        ("dim_customer", ["customer_id", "rep_id"]),
        ("dim_date", ["date_key", "month_num", "quarter", "year"]),
    ]:
        for column in columns:
            series = tables[name][column].dropna()
            if len(series) == 0:
                continue
            fractional = (series % 1 != 0).sum()
            assert fractional == 0, (
                f"{name}.{column} contains {fractional} fractional values — "
                "a key or count has been upcast to float"
            )


def test_foreign_keys_resolve_except_where_defects_were_injected(tables):
    """Every fact foreign key must point at a real dimension row.

    dim_customer.region_id is the documented exception: blanking three of them
    is an injected defect, and the analysis is expected to catch and repair it.
    """
    fact = tables["fact_subscription_monthly"]
    assert fact["customer_id"].isin(tables["dim_customer"]["customer_id"]).all()
    assert fact["plan_id"].isin(tables["dim_plan"]["plan_id"]).all()
    assert fact["date_key"].isin(tables["dim_date"]["date_key"]).all()

    broken = tables["dim_customer"]["region_id"].isna().sum()
    assert broken == config.DEFECT_CUSTOMER_BLANK_REGION, (
        "The broken-foreign-key defect has changed size; the repair step and "
        "the data-quality report both depend on this count"
    )


def test_sqlite_database_opens_and_counts_match(tables):
    """The SQLite mirror must exist and agree with the CSVs."""
    assert os.path.exists(config.SQLITE_PATH), "saas_revenue.db was not written"
    conn = sqlite3.connect(config.SQLITE_PATH)
    try:
        for name, df in tables.items():
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            assert count == len(df), (
                f"{name}: SQLite has {count} rows, CSV has {len(df)}"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Leakage
# ---------------------------------------------------------------------------

def test_churn_is_not_a_column_on_the_fact_table(tables):
    """Churn must be derived from the panel, never stored on a monthly row.

    A boolean `is_churned` on a month-1 fact row would let the row "know" the
    customer leaves in month 3. Any model trained on it would score near 1.0
    and prove nothing.
    """
    fact_columns = set(tables["fact_subscription_monthly"].columns)
    for leaked in ("is_churned", "churned", "churn", "churned_month"):
        assert leaked not in fact_columns, (
            f"'{leaked}' is on the fact table — this is target leakage"
        )


def test_churn_reason_is_post_hoc_and_confined_to_the_dimension(tables):
    """The churn reason is recorded after departure and cannot be a feature."""
    assert "churn_reason_id" in tables["dim_customer"].columns
    assert "churn_reason_id" not in tables["fact_subscription_monthly"].columns

    # * Only customers who left may have a reason.
    churned = tables["dim_customer"]["churned_month"].notna()
    has_reason = tables["dim_customer"]["churn_reason_id"].notna()
    assert (has_reason & ~churned).sum() == 0, (
        "A customer who did not churn has a churn reason"
    )


def test_observation_window_is_available_for_every_customer(tables):
    """Every customer has the first two months, so a fixed baseline is possible.

    This is what allows features to be built from a FIXED window rather than
    "however many months the customer happens to have" -- the latter is the
    outcome leaking into the features, since churners have fewer rows by
    construction.
    """
    # * drop_duplicates removes the injected duplicate block. subset=["fact_id"]
    # * means "two rows are duplicates if their fact_id matches", which is the
    # * primary key and therefore the correct definition here. keep="first"
    # * (the default) retains the earliest copy.
    fact = tables["fact_subscription_monthly"].drop_duplicates(subset=["fact_id"])
    first_two = fact[fact["date_key"].isin(config.MONTHS[:2])]
    customers_with_baseline = first_two["customer_id"].nunique()
    total_customers = tables["dim_customer"]["customer_id"].nunique()
    assert customers_with_baseline == total_customers, (
        f"Only {customers_with_baseline} of {total_customers} customers have the "
        "2-month baseline window; features would be built on unequal exposure"
    )


# ---------------------------------------------------------------------------
# 3. Signal — can a model recover the generating process?
# ---------------------------------------------------------------------------

def _clean_fact(fact):
    """Apply the minimum repairs the analysis is expected to perform."""
    # ? .copy() is deliberate. Slicing a DataFrame returns a VIEW, and writing
    # ? to a view raises a SettingWithCopyWarning and may not affect the
    # ? original at all. .copy() makes this an independent frame so the edits
    # ? below are guaranteed to stick.
    fact = fact.drop_duplicates(subset=["fact_id"], keep="first").copy()
    # * Impossible values become missing, to be imputed rather than averaged in.
    fact.loc[fact["usage_events"] < 0, "usage_events"] = np.nan
    # * A discount above 1.0 is the injected defect; the true value is 1 less.
    over = fact["discount_pct"] > 1.0
    fact.loc[over, "discount_pct"] = fact.loc[over, "discount_pct"] - 1.0
    fact["usage_per_seat"] = fact["usage_events"] / fact["seats"].clip(lower=1)
    return fact


def _baseline_features(tables):
    """Build customer-level features from the FIXED 2-month baseline window."""
    fact = _clean_fact(tables["fact_subscription_monthly"])
    # * config.MONTHS[:2] is the first two months -- the FIXED baseline window.
    # * Using a fixed window matters: a churner has fewer rows by construction,
    # * so "all the months they happen to have" would leak the outcome straight
    # * into the features.
    baseline = fact[fact["date_key"].isin(config.MONTHS[:2])]

    # * One row per customer: usage and sentiment averaged over the window, and
    # * the ticket RATE (mean per month) rather than a total, because a total is
    # * confounded by the number of months observed.
    agg = baseline.groupby("customer_id").agg(
        mean_usage_per_seat=("usage_per_seat", "mean"),
        # ! ticket RATE, not the sum. A sum is confounded by how many months a
        # ! customer has, which is the outcome. The rate is comparable.
        ticket_rate=("support_tickets", "mean"),
        mean_discount=("discount_pct", "mean"),
        mean_nps=("nps_score", "mean"),
    ).reset_index()
    # ? how="inner" keeps only customers present in both frames. Here that is
    # ? intentional: a customer with no baseline rows cannot have baseline
    # ? features, so there is nothing to model.
    merged = tables["dim_customer"].merge(agg, on="customer_id", how="inner")

    # * .map(dict) translates each industry name into its risk number.
    risk = {d["industry"]: d["churn_risk_index"] for d in config.INDUSTRIES}
    merged["industry_risk"] = merged["industry"].map(risk)

    # * .astype(int) converts True/False into 1/0 for the model.
    merged["is_smb"] = (merged["segment"] == "SMB").astype(int)

    # * THE LABEL. .notna() is True when churned_month holds a real value, i.e.
    # * the customer left. This is the only place churn is defined, and it is
    # * derived from the panel -- never read from a stored column.
    merged["is_churned"] = merged["churned_month"].notna().astype(int)
    return merged.dropna(subset=["mean_usage_per_seat", "mean_discount", "industry_risk"])


def test_churn_rate_is_close_to_the_designed_rate(tables):
    """The panel must produce roughly the target churn rate."""
    customers = tables["dim_customer"]
    rate = customers["churned_month"].notna().mean()
    assert abs(rate - config.TARGET_CHURN_RATE) < 0.03, (
        f"Churn rate is {rate:.3f}, expected about {config.TARGET_CHURN_RATE}"
    )


def test_there_are_enough_positives_to_fit_a_classifier(tables):
    """Too few churners and every metric becomes unstable between seeds."""
    positives = tables["dim_customer"]["churned_month"].notna().sum()
    assert positives >= 25, (
        f"Only {positives} churners; ROC-AUC will swing by several points on a "
        "different seed and the results will not be meaningful"
    )


def test_features_separate_churners_from_stayers(tables):
    """Usage and sentiment must differ between the two groups, as designed.

    This is a weak but fast guard: if a future change to the generator removes
    the signal, it fails here rather than after a full training run.
    """
    merged = _baseline_features(tables)
    churned = merged[merged["is_churned"] == 1]
    stayed = merged[merged["is_churned"] == 0]
    assert churned["mean_usage_per_seat"].mean() < stayed["mean_usage_per_seat"].mean(), (
        "Churners are not using the product less than stayers — the usage signal is gone"
    )
    assert churned["mean_nps"].mean() < stayed["mean_nps"].mean(), (
        "Churners do not report lower NPS than stayers — the sentiment signal is gone"
    )


def test_logistic_regression_recovers_the_designed_coefficients(tables):
    """The strongest test in the file: does the model find the true process?

    The data is synthetic, so the coefficients that generated churn are known
    (config.TRUE_CHURN_COEFFICIENTS). A fitted logistic regression on a fixed
    baseline window should agree in SIGN with the design.

    Only signs are asserted. Magnitudes cannot match: the truth is expressed on
    the raw scale and the fit uses standardised features, and the fitted values
    are conditional on the other features in the model.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    merged = _baseline_features(tables)

    # ! USE EVERY FEATURE THAT GENERATED THE LABEL. DO NOT SUBSET THEM.
    # !
    # ! An earlier version of this test fitted only four features, leaving out
    # ! `mean_usage_per_seat`. That looked harmless and was not: usage per seat
    # ! is by far the strongest predictor in the design, so removing it left the
    # ! model with too little signal to estimate the SMALLER effects reliably.
    # ! `is_smb` has a true coefficient of +0.55 and came out at -0.025 — the
    # ! right order of magnitude for noise, and the wrong sign.
    # !
    # ! The lesson generalises: a coefficient is only interpretable in the model
    # ! it was estimated in. Omit the dominant variable and every remaining
    # ! coefficient absorbs part of its absence and stops meaning anything. The
    # ! test was wrong, not the data — and it failed loudly, which is the point.
    features = [
        "mean_usage_per_seat",
        "ticket_rate",
        "mean_discount",
        "mean_nps",
        "is_smb",
        "industry_risk",
        "is_annual_contract",
    ]
    X = StandardScaler().fit_transform(merged[features])
    y = merged["is_churned"].to_numpy()

    model = LogisticRegression(max_iter=2000).fit(X, y)
    fitted = dict(zip(features, model.coef_[0]))

    # * Each feature, and the config key holding the coefficient that actually
    # * generated churn. All seven are checked, not a subset.
    truth = config.TRUE_CHURN_COEFFICIENTS
    for feature, key in [
        ("mean_usage_per_seat", "usage_per_seat"),
        ("ticket_rate", "support_tickets"),
        ("mean_discount", "discount_pct"),
        ("mean_nps", "nps_score"),
        ("is_smb", "is_smb"),
        ("industry_risk", "industry_risk"),
        ("is_annual_contract", "is_annual_contract"),
    ]:
        assert np.sign(fitted[feature]) == np.sign(truth[key]), (
            f"{feature}: fitted {fitted[feature]:+.3f} but the generating "
            f"coefficient is {truth[key]:+.3f}. The model cannot recover the "
            "process that produced the data — do not trust the analysis."
        )


def test_discount_shows_confounding_marginal_versus_conditional(tables):
    """Discount illustrates why univariate correlation misleads.

    Discount is correlated with segment and usage, so its MARGINAL correlation
    with churn is near zero while its CONDITIONAL coefficient is positive. This
    test pins that finding down, because it is one of the analysis's headline
    results and it would be silent if the feature set changed.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    merged = _baseline_features(tables)
    marginal = merged["mean_discount"].corr(merged["is_churned"])

    features = ["mean_usage_per_seat", "ticket_rate", "mean_discount",
                "mean_nps", "is_smb", "industry_risk", "is_annual_contract"]
    X = StandardScaler().fit_transform(merged[features])
    y = merged["is_churned"].to_numpy()
    model = LogisticRegression(max_iter=2000).fit(X, y)
    conditional = dict(zip(features, model.coef_[0]))["mean_discount"]

    assert conditional > 0, (
        "The conditional discount coefficient should be positive, matching the "
        f"generating process. Got {conditional:+.3f}"
    )
    assert abs(marginal) < abs(conditional), (
        f"Marginal correlation ({marginal:+.3f}) should be weaker than the "
        f"conditional coefficient ({conditional:+.3f}) — that gap IS the finding"
    )


# ---------------------------------------------------------------------------
# 4. Reporting artefacts
# ---------------------------------------------------------------------------

def test_data_quality_report_lists_every_injected_defect():
    """The defect inventory is the contract between generator and analysis."""
    path = os.path.join(config.REPORTS_DIR, "data_quality.json")
    assert os.path.exists(path), "data_quality.json was not written"
    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)

    assert report["rows_under_cap"] is True
    assert len(report["defects_injected"]) == 8, (
        f"Expected 8 documented defects, found {len(report['defects_injected'])}"
    )
    for defect in report["defects_injected"]:
        for field in ("table", "column", "defect", "rows_affected", "breaks"):
            assert field in defect, f"Defect record missing '{field}': {defect}"


def test_leakage_warning_is_recorded_for_the_reader():
    """The report must carry the leakage rule forward to whoever reads it."""
    path = os.path.join(config.REPORTS_DIR, "data_quality.json")
    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)
    assert "derived from the panel" in report["leakage_warning"]
