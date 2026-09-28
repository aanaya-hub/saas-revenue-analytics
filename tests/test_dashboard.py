"""
test_dashboard.py — tests for the dashboard and the payload it reads.

Run with:  python -m pytest -q

WHY THE DASHBOARD NEEDS ITS OWN TESTS
The dashboard is the only part of this project a visitor actually sees, and it
is the part with the least obvious failure mode. A broken model throws an
exception; a broken chart renders an empty axes and looks fine. These tests
check the callbacks return sensible structures rather than nothing, and that the
numbers on screen agree with the numbers the analysis produced.

The most important test here is `test_dashboard_imports_no_heavy_libraries`.
The deployment target caps a Python bundle at 500 MB and the analysis stack is
close to 1 GB, so a single stray `import sklearn` at the top of dashboard.py
would silently make the project undeployable. That is a constraint with no
runtime symptom until deploy day, which makes it exactly the kind of thing that
belongs in a test.
"""

import importlib
import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402

RESULTS_PATH = os.path.join(config.REPORTS_DIR, "results.json")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dashboard():
    """Import dashboard.py once, or skip if the results file is missing.

    Importing the module is safe: `app.run()` sits behind an
    `if __name__ == "__main__"` guard, so no server starts.
    """
    if not os.path.exists(RESULTS_PATH):
        pytest.skip("reports/results.json not found — run `python analysis.py` first")
    return importlib.import_module("dashboard")


@pytest.fixture(scope="module")
def results():
    """The raw contents of reports/results.json.

    A separate fixture from `dashboard` because some tests check the FILE while
    others check the code that reads it. Keeping them apart means a test that
    inspects the published numbers cannot accidentally pass by exercising the
    dashboard's own parsing.
    """
    with open(RESULTS_PATH, encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# 1. The payload the dashboard depends on
# ---------------------------------------------------------------------------

def test_results_file_contains_a_dashboard_payload(results):
    """analysis.py must publish everything the dashboard renders."""
    assert "dashboard" in results, "results.json has no 'dashboard' section"
    payload = results["dashboard"]
    for key in ("monthly_revenue", "revenue_by_segment", "revenue_by_region",
                "revenue_by_industry", "customers", "cluster_summary"):
        assert key in payload, f"dashboard payload is missing '{key}'"
        assert len(payload[key]) > 0, f"dashboard payload '{key}' is empty"


def test_every_customer_has_the_fields_the_table_displays(results):
    """The risk table reads nine fields per customer; a missing one is a blank cell."""
    required = {"customer_id", "company", "segment", "industry", "region", "seats",
                "mrr", "usage_per_seat", "nps_score", "discount_pct",
                "churn_probability", "risk_band", "actual_churn", "cluster"}
    for customer in results["dashboard"]["customers"]:
        missing = required - set(customer)
        assert not missing, f"customer {customer.get('customer_id')} missing {missing}"


def test_customers_are_sorted_riskiest_first(results):
    """The call list opens on the accounts that matter, so the sort is load-bearing."""
    probabilities = [row["churn_probability"] for row in results["dashboard"]["customers"]]
    assert probabilities == sorted(probabilities, reverse=True), (
        "the customer list is not sorted by churn probability"
    )


def test_churn_probabilities_are_valid_and_cover_everyone(results):
    """Two hundred scores, each a genuine probability."""
    probabilities = [row["churn_probability"] for row in results["dashboard"]["customers"]]
    assert len(probabilities) == 200
    assert all(0.0 <= value <= 1.0 for value in probabilities), (
        "a churn probability falls outside 0-1, so it is not a probability"
    )


def test_risk_bands_agree_with_the_probabilities(results):
    """The band is derived from the number, so the two must not contradict."""
    for customer in results["dashboard"]["customers"]:
        probability = customer["churn_probability"]
        band = customer["risk_band"]
        if probability >= 0.60:
            assert band == "High", f"{probability:.2f} should be High, got {band}"
        elif probability >= 0.30:
            assert band == "Medium", f"{probability:.2f} should be Medium, got {band}"
        else:
            assert band == "Low", f"{probability:.2f} should be Low, got {band}"


def test_monthly_revenue_matches_the_analysis(results):
    """The executive chart must plot the same months the analysis reported."""
    monthly = results["dashboard"]["monthly_revenue"]
    assert len(monthly) == results["revenue"]["months"]
    first, last = monthly[0], monthly[-1]
    assert first["mrr"] == pytest.approx(results["revenue"]["mrr_first_month"], rel=1e-4)
    assert last["mrr"] == pytest.approx(results["revenue"]["mrr_last_month"], rel=1e-4)


# ---------------------------------------------------------------------------
# 2. The deployment constraint
# ---------------------------------------------------------------------------

def test_dashboard_imports_no_heavy_libraries():
    """dashboard.py must not import the analysis stack.

    Checked by reading the SOURCE rather than by importing, so the test cannot
    be fooled by import order or by a module already being in memory from
    another test.
    """
    import ast

    source = open(os.path.join(PROJECT_ROOT, "dashboard.py"), encoding="utf-8").read()
    tree = ast.parse(source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    heavy = {"sklearn", "matplotlib", "scipy", "xgboost", "statsmodels",
             "hdbscan", "umap", "seaborn", "numpy", "pandas", "PIL", "wordcloud"}
    offending = imported & heavy
    assert not offending, (
        f"dashboard.py imports {offending}. These must stay in analysis.py: "
        "the deployment bundle limit is 500 MB and this stack is close to 1 GB."
    )


def test_the_dashboard_only_imports_what_it_should():
    """A whitelist, so an unexpected import is noticed rather than deployed."""
    import ast

    source = open(os.path.join(PROJECT_ROOT, "dashboard.py"), encoding="utf-8").read()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    # * pandas was removed on 2026-09-27. It was used in four places, all of
    # * which plain Python handles, and it was pulling NumPy into the deployment
    # * bundle for no benefit.
    allowed = {"dash", "plotly", "json", "os", "datetime", "math"}
    unexpected = imported - allowed
    assert not unexpected, (
        f"dashboard.py imports {unexpected}, which is outside the agreed set {allowed}. "
        "If this is deliberate, add it here with a reason."
    )


# ---------------------------------------------------------------------------
# 3. The callbacks
# ---------------------------------------------------------------------------

def test_every_tab_renders(dashboard):
    """Five tabs, five non-empty layouts."""
    for tab in ("executive", "revenue", "churn", "segments", "quality"):
        node = dashboard.render_tab(tab)
        assert node is not None, f"tab '{tab}' rendered nothing"


def test_threshold_callback_counts_are_internally_consistent(dashboard):
    """The four outcomes must account for every customer, at any threshold."""
    total = len(dashboard.DASH["customers"])
    for threshold in (0.10, 0.25, 0.50, 0.75, 0.90):
        stats = dashboard.confusion_at(threshold)
        assert stats["tp"] + stats["fp"] + stats["fn"] + stats["tn"] == total, (
            f"at threshold {threshold} the confusion matrix does not sum to {total}"
        )


def test_lowering_the_threshold_catches_more_churners(dashboard):
    """The central claim of the churn tab, asserted rather than assumed."""
    low = dashboard.confusion_at(0.20)
    high = dashboard.confusion_at(0.70)
    assert low["recall"] > high["recall"], (
        "a lower threshold should catch at least as many churners"
    )
    assert low["fn"] <= high["fn"], "a lower threshold should miss no more churners"


def test_the_cost_model_is_read_from_the_results_file(dashboard, results):
    """The dashboard must not hardcode the costs it is arguing about.

    If it did, editing the assumption in analysis.py would leave the dashboard
    quietly presenting the old argument.
    """
    published = results["modelling"]["classification"]["threshold_analysis"]["cost_assumptions"]
    assert dashboard.COST["missed_churner"] == published["missed_churner"]
    assert dashboard.COST["false_alarm"] == published["false_alarm"]


def test_the_default_threshold_costs_more_than_the_optimum(dashboard, results):
    """Reproduce the headline saving through the dashboard's own code path.

    The analysis reports a saving from moving 0.50 to the cost-optimal threshold.
    This checks the dashboard computes the same thing — two independent code
    paths agreeing is a stronger result than either one alone.
    """
    analysis = results["modelling"]["classification"]["threshold_analysis"]
    at_default = dashboard.confusion_at(0.50)
    at_optimal = dashboard.confusion_at(analysis["optimal_threshold"])
    saving = at_default["cost"] - at_optimal["cost"]
    assert saving == pytest.approx(analysis["saving_vs_default"], rel=0.02), (
        f"dashboard computes a saving of ${saving:,.0f} but the analysis reported "
        f"${analysis['saving_vs_default']:,.0f}"
    )


def test_revenue_callback_returns_a_bar_per_category(dashboard):
    """Every grouping produces one bar per category, not an empty chart."""
    for dimension in ("revenue_by_segment", "revenue_by_region", "revenue_by_industry"):
        figure = dashboard.update_revenue_chart(dimension)
        expected = len(dashboard.DASH[dimension])
        assert len(figure["data"][0]["x"]) == expected, (
            f"{dimension}: chart has {len(figure['data'][0]['x'])} bars, "
            f"expected {expected}"
        )


def test_segment_scatter_covers_every_customer(dashboard):
    """No customer may be dropped from the scatter."""
    figure = dashboard.draw_segment_scatter("segments")
    plotted = sum(len(trace["x"]) for trace in figure["data"])
    assert plotted == len(dashboard.DASH["customers"])


def test_segment_callbacks_do_nothing_on_other_tabs(dashboard):
    """The guard prevents needless work when the Segments tab is not open."""
    assert dashboard.draw_segment_scatter("executive") is dashboard.no_update
    assert dashboard.draw_segment_profile("quality") is dashboard.no_update


# ---------------------------------------------------------------------------
# 4. The executive tab's headline numbers
# ---------------------------------------------------------------------------

def test_executive_tab_reports_accumulated_revenue(dashboard, results):
    """The window total must appear on the executive tab.

    Accumulated revenue is the "how big is this business" figure, and it is a
    DIFFERENT quantity from the monthly rates shown beside it — a total, not a
    rate. It was missing from the first version of this tab, which left the
    page showing only per-month movement and no sense of the whole window.
    """
    text = str(dashboard.executive_tab())
    total = results["revenue"]["total_mrr"]
    assert f"${total:,.0f}" in text, (
        f"accumulated revenue (${total:,.0f}) is not on the executive tab"
    )
    assert "Revenue, 4 months" in text, "the accumulated revenue KPI has no label"


def test_accumulated_revenue_equals_the_sum_of_the_months(dashboard, results):
    """The published total must agree with the monthly series it summarises.

    Two numbers describing the same thing is a licence for them to disagree. If
    the monthly series were ever recalculated, this catches a stale total.
    """
    monthly_total = sum(row["mrr"] for row in results["dashboard"]["monthly_revenue"])
    published = results["revenue"]["total_mrr"]
    assert monthly_total == pytest.approx(published, rel=1e-6), (
        f"monthly series sums to ${monthly_total:,.2f} but the reported total is "
        f"${published:,.2f}"
    )


def test_trend_chart_shows_both_monthly_and_accumulated(dashboard):
    """One chart, two readings: the month's revenue and the running total."""
    figure = dashboard.executive_tab().children[1].children[0].figure
    names = [trace.get("name") for trace in figure["data"]]
    assert "Revenue that month" in names, "the monthly bars are missing"
    assert "Accumulated" in names, "the cumulative line is missing"

    cumulative = next(t for t in figure["data"] if t.get("name") == "Accumulated")
    # * A cumulative series must be non-decreasing: revenue only adds up.
    assert all(b >= a for a, b in zip(cumulative["y"], cumulative["y"][1:])), (
        "the accumulated series decreases, which is impossible for a running total"
    )


def test_trend_chart_final_point_equals_the_headline_total(dashboard, results):
    """The line's last point is the number in the KPI card above it."""
    figure = dashboard.executive_tab().children[1].children[0].figure
    cumulative = next(t for t in figure["data"] if t.get("name") == "Accumulated")
    assert cumulative["y"][-1] == pytest.approx(results["revenue"]["total_mrr"], rel=1e-6)


# ---------------------------------------------------------------------------
# 5. The serverless entry point
# ---------------------------------------------------------------------------
# These tests exist because the deployment entry point fails in a way that is
# invisible until it is live. A missing `app`, or an `app` that is not a WSGI
# callable, still builds successfully on Vercel and then returns 500 for every
# request with nothing useful in the logs.

ENTRY_PATH = os.path.join(PROJECT_ROOT, "api", "index.py")


def _load_entry_point():
    """Import api/index.py by path, since it is not a package on sys.path."""
    import importlib.util

    if not os.path.exists(ENTRY_PATH):
        pytest.skip("api/index.py not present — nothing to deploy")
    spec = importlib.util.spec_from_file_location("vercel_entry", ENTRY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entry_point_exposes_a_wsgi_callable():
    """Vercel looks for a module-level name `app` and treats it as the handler."""
    entry = _load_entry_point()
    assert hasattr(entry, "app"), (
        "api/index.py has no `app`. Vercel requires that exact name — it builds "
        "successfully without it and then returns 500 for every request."
    )
    assert callable(entry.app), "`app` exists but is not callable, so it is not a WSGI app"


def test_entry_point_app_is_the_dash_flask_server(dashboard):
    """The handler must be the Dash Flask instance, not the Dash object.

    `dash.Dash` is not a WSGI application; `dash.Dash().server` is. Exposing the
    wrong one is the most common way this file is written incorrectly.
    """
    entry = _load_entry_point()
    assert entry.app is dashboard.app.server, (
        "api/index.py exposes something other than dashboard.app.server"
    )


def test_entry_point_answers_a_real_request():
    """Serve one request straight through the WSGI interface — no server needed.

    wsgiref builds a valid, empty request environment; calling the app with it
    exercises the same code path a live HTTP request would, without binding a
    port or waiting for a network round trip.
    """
    from wsgiref.util import setup_testing_defaults

    entry = _load_entry_point()
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = "GET"
    environ["PATH_INFO"] = "/"

    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(entry.app(environ, start_response))

    assert captured["status"].startswith("200"), f"got status {captured['status']}"
    assert b"Northwind Analytics" in body, "the served page does not contain the app title"


def test_entry_point_serves_the_dash_callback_endpoints():
    """Dash fetches its layout and dependency graph from separate URLs.

    A deployment that serves `/` but not `/_dash-layout` renders an empty page,
    which looks like a styling problem rather than a routing one.
    """
    from wsgiref.util import setup_testing_defaults

    entry = _load_entry_point()
    for path in ("/_dash-layout", "/_dash-dependencies"):
        environ = {}
        setup_testing_defaults(environ)
        environ["REQUEST_METHOD"] = "GET"
        environ["PATH_INFO"] = path

        captured = {}
        body = b"".join(entry.app(environ,
                                  lambda s, h: captured.update(status=s)))
        assert captured["status"].startswith("200"), f"{path} returned {captured['status']}"
        assert len(body) > 100, f"{path} returned an empty body"
