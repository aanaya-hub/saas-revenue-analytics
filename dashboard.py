"""
dashboard.py — the interactive front end for the SaaS revenue analysis.

WHAT THIS FILE IS
A Plotly Dash web application: five tabs over the results that analysis.py has
already computed. It reads reports/results.json and draws charts in the browser.

HOW TO RUN IT
    make serve          or          ./venv-saas/bin/python dashboard.py
Then open http://127.0.0.1:8050

WHY THIS FILE IMPORTS SO LITTLE
    It imports dash and plotly. That is the whole list.

An earlier version also imported pandas, to hold the 200 customers in a
DataFrame. It was used in exactly four places — filtering a list, summing a
column, and taking a set of cluster ids — all of which plain Python does. In a
notebook that would be a style question; here it is 64 MB of the deployment
bundle, because pandas brings NumPy with it.

Three separate reasons, and all three matter:

  1. DEPLOYMENT SIZE. The target host caps a Python bundle at 500 MB. The
     analysis stack — xgboost alone is about 200 MB — is roughly 1 GB. Importing
     scikit-learn here would make the site undeployable.

  2. SPEED. Models are trained in analysis.py, not here. Moving a slider does
     arithmetic on 200 stored numbers, which is instant. Retraining on every
     interaction would make the page unusable and the cost absurd.

  3. HONESTY. Every number shown was computed once, in one place, by code with
     tests. A dashboard free to recompute is a dashboard free to disagree with
     the report it is supposed to be presenting.

ARCHITECTURE IN ONE LINE
    analysis.py writes numbers to JSON; this file reads those numbers and draws
    them. The two never share code, and that is deliberate.

THE CORPUS IMPORTS USED HERE
    import dash
    from dash import html, dcc
    from dash.dependencies import Input, Output, State
These are exactly the four import forms the certification's seven dashboard
artefacts use, which is why the tables are built from html.Table rather than
from the optional dash_table component.
"""

# ============================================================================
# IMPORTS — deliberately short
# ============================================================================
import json          # reads reports/results.json
import os            # builds the path to that file portably

import dash                                  # the application object itself
from dash import html, dcc                   # page structure and interactive controls
from dash.dependencies import Input, Output  # wires a control to a callback
from dash import no_update                    # "leave this output unchanged"

# ============================================================================
# DATA — read once, at import time
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(BASE_DIR, "reports", "results.json")

# * Fail loudly and helpfully if the analysis has not been run. A dashboard that
# * starts and then shows empty charts is far harder to diagnose than one that
# * refuses to start and says what to do.
if not os.path.exists(RESULTS_PATH):
    raise SystemExit(
        "reports/results.json not found.\n"
        "The dashboard reads results that analysis.py produces.\n"
        "Run `make analyse` (or `python analysis.py`) first."
    )

with open(RESULTS_PATH, encoding="utf-8") as handle:
    RESULTS = json.load(handle)

DASH = RESULTS["dashboard"]
# * A plain list of dictionaries, exactly as it was written to JSON. No
# * DataFrame: this file only ever filters, sums and takes sets, and pandas
# * would add 64 MB to the deployment bundle to do it.
CUSTOMERS = DASH["customers"]

# * Precomputed once at import rather than on every request. The bands never
# * change, and recomputing them inside a callback would repeat the same work
# * on every slider movement.
HIGH_RISK = [customer for customer in CUSTOMERS if customer["risk_band"] == "High"]
COST = RESULTS["modelling"]["classification"]["threshold_analysis"]["cost_assumptions"]
REPAIRS = RESULTS["repairs"]
CHURN = RESULTS["churn"]

# ============================================================================
# STYLE — one place, so the pages look like one application
# ============================================================================

BRAND = "#2E5EAA"
ACCENT = "#E4572E"
GREEN = "#17B890"
INK = "#1F2933"
MUTED = "#6B7280"

CARD = {
    "backgroundColor": "#FFFFFF",
    "border": f"1px solid #E5E7EB",
    "borderRadius": "10px",
    "padding": "18px 20px",
    "marginBottom": "16px",
}
PAGE = {"maxWidth": "1280px", "margin": "0 auto", "padding": "26px 20px",
        "fontFamily": "Inter, Segoe UI, system-ui, sans-serif", "color": INK}
H2 = {"fontSize": "15px", "fontWeight": 600, "marginTop": 0, "marginBottom": "14px",
      "color": MUTED, "textTransform": "uppercase", "letterSpacing": "0.04em"}

PLOT_LAYOUT = {
    "margin": {"l": 60, "r": 24, "t": 30, "b": 50},
    "plot_bgcolor": "white",
    "paper_bgcolor": "white",
    "font": {"family": "Inter, Segoe UI, system-ui, sans-serif", "color": INK},
}


def kpi(label, value, note=""):
    """One headline figure, with a small caption underneath.

    WHY A HELPER RATHER THAN REPEATED MARKUP
    The executive tab shows six of these. Written out longhand that is sixty
    lines of near-identical html.Div nesting, and a change to the styling means
    six edits that will eventually disagree. One function, one appearance.
    """
    return html.Div([
        html.Div(label, style={"fontSize": "12px", "color": MUTED,
                               "textTransform": "uppercase", "letterSpacing": "0.05em"}),
        html.Div(value, style={"fontSize": "28px", "fontWeight": 700,
                               "marginTop": "6px", "color": BRAND}),
        html.Div(note, style={"fontSize": "12px", "color": MUTED, "marginTop": "4px"}),
    ], style={"flex": "1", "minWidth": "170px", "padding": "6px 0"})


def simple_table(headers, rows):
    """Build an HTML table from a list of header strings and a list of rows.

    WHY NOT dash_table
    The optional `dash_table` component is not among the imports used anywhere in
    the certification's dashboard artefacts, and adding it would mean the project
    claims a library the coursework never covered. Plain html.Table components
    produce a perfectly readable table with nothing extra to install.
    """
    return html.Table([
        html.Thead(html.Tr([
            html.Th(header, style={
                "textAlign": "left", "padding": "8px 12px", "borderBottom": f"2px solid {BRAND}",
                "fontSize": "12px", "textTransform": "uppercase", "color": MUTED,
                "letterSpacing": "0.04em",
            }) for header in headers
        ])),
        html.Tbody([
            html.Tr([
                html.Td(cell, style={"padding": "7px 12px", "borderBottom": "1px solid #F0F1F3",
                                     "fontSize": "13px"})
                for cell in row
            ]) for row in rows
        ]),
    ], style={"width": "100%", "borderCollapse": "collapse"})


# ============================================================================
# TAB 1 — EXECUTIVE
# ============================================================================

def executive_tab():
    """The four numbers a director asks for, then the two charts behind them.

    Ordered by the question a reader arrives with: how big is the business, is
    it growing, how many customers are leaving, and what is at stake. The charts
    come after the numbers because a chart makes you work to extract a figure,
    and a KPI does not.
    """
    revenue = RESULTS["revenue"]
    monthly = DASH["monthly_revenue"]

    first, last = monthly[0], monthly[-1]
    change = (last["mrr"] - first["mrr"]) / first["mrr"] * 100

    # * Accumulated revenue across the whole window. This is the "how big is
    # * this business" number, and it is DIFFERENT from the monthly MRR figures
    # * below it: those are rates (dollars per month), this is the total billed
    # * over the four months. Presenting a rate and a total without labelling
    # * which is which is one of the easiest ways to mislead an audience.
    total_revenue = revenue["total_mrr"]

    # * Annualised run-rate: the latest month multiplied by twelve. It answers
    # * "what would a year look like at the current pace" and is NOT a forecast —
    # * revenue is falling, so extrapolating would be wrong. Labelled as a rate
    # * for that reason.
    annualised = last["mrr"] * 12

    cards = html.Div([
        kpi("Revenue, 4 months", f"${total_revenue:,.0f}",
            f"accumulated across {revenue['customers']} customers"),
        kpi("MRR, latest month", f"${last['mrr']:,.0f}", f"as at {last['month']}"),
        kpi("Annualised run-rate", f"${annualised:,.0f}",
            "latest month x 12 — a rate, not a forecast"),
        kpi("Change over the window", f"{change:+.1f}%",
            f"from ${first['mrr']:,.0f} in {first['month']}"),
        kpi("Customers", f"{revenue['customers']}", "in the analysis window"),
        kpi("Churn rate", f"{CHURN['overall_churn_rate']:.1%}",
            f"{CHURN['churned_customers']} of "
            f"{CHURN['churned_customers'] + CHURN['retained_customers']} left"),
        kpi("Top 10% hold",
            f"{RESULTS['concentration']['top_10_pct_share_of_mrr']:.0%}",
            "of all revenue"),
        kpi("Revenue at risk",
            f"${sum(customer['mrr'] for customer in HIGH_RISK):,.0f}",
            f"per month, across {len(HIGH_RISK)} high-risk accounts"),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "18px", "marginBottom": "10px"})

    # --- Revenue trend, and the accumulation ---------------------------------
    # * Two series on one chart, deliberately:
    # *   bars  = revenue in THAT month (a rate)
    # *   line  = the running total so far (accumulated)
    # * They answer different questions, and a reader who sees only the bars has
    # * no sense of the size of the whole window. A dual axis is used because
    # * the two are different quantities — but both are dollars, both are
    # * labelled, and the line's shape is the interesting part: it flattens as
    # * churn starts eating into each month's contribution.
    months = [row["month"] for row in monthly]
    monthly_values = [row["mrr"] for row in monthly]

    running_total = []
    cumulative = 0.0
    for value in monthly_values:
        cumulative += value
        running_total.append(cumulative)

    trend = {
        "data": [
            {
                "x": months, "y": monthly_values,
                "type": "bar", "name": "Revenue that month",
                "marker": {"color": "#C7D5EC"},
                "text": [f"${value / 1000:,.0f}k" for value in monthly_values],
                "textposition": "inside",
                "hovertemplate": "%{x}<br>that month $%{y:,.0f}<extra></extra>",
            },
            {
                "x": months, "y": running_total,
                "type": "scatter", "mode": "lines+markers+text",
                "name": "Accumulated", "yaxis": "y2",
                "line": {"color": BRAND, "width": 3.5},
                "marker": {"size": 10},
                "text": [f"${value / 1_000_000:,.2f}M" for value in running_total],
                "textposition": "top center",
                "hovertemplate": "%{x}<br>accumulated $%{y:,.0f}<extra></extra>",
            },
        ],
        "layout": {
            **PLOT_LAYOUT,
            "title": "Revenue by month, and the total accumulated",
            "barmode": "overlay",
            "yaxis": {"title": "Revenue that month (USD)", "rangemode": "tozero"},
            # * yaxis2 is the right-hand axis, overlaid rather than stacked.
            "yaxis2": {"title": "Accumulated (USD)", "overlaying": "y",
                       "side": "right", "rangemode": "tozero", "showgrid": False},
            "xaxis": {"title": ""},
            "legend": {"orientation": "h", "y": 1.12, "x": 0},
            "height": 380,
        },
    }

    # --- Revenue split by segment -------------------------------------------
    by_segment = DASH["revenue_by_segment"]
    split = {
        "data": [{
            "x": [row["category"] for row in by_segment],
            "y": [row["mrr"] for row in by_segment],
            "type": "bar",
            "marker": {"color": [BRAND, GREEN, ACCENT][:len(by_segment)]},
            "text": [f"${row['mrr'] / 1000:,.0f}k" for row in by_segment],
            "textposition": "outside",
            "hovertemplate": "%{x}<br>$%{y:,.0f}<extra></extra>",
        }],
        "layout": {**PLOT_LAYOUT, "title": "Revenue by segment",
                   "yaxis": {"title": "MRR (USD)"}, "xaxis": {"title": ""},
                   "height": 320},
    }

    return html.Div([
        html.Div([html.H2("The business at a glance"), cards], style=CARD),
        html.Div([dcc.Graph(figure=trend)], style=CARD),
        html.Div([dcc.Graph(figure=split)], style=CARD),
    ])


# ============================================================================
# TAB 2 — REVENUE DETAIL
# ============================================================================

def revenue_tab():
    """A dropdown that re-slices revenue by segment, region or industry.

    This is the simplest useful callback in Dash: one Input (the dropdown), one
    Output (the graph). It exists to show that the interactivity is real rather
    than decorative — the chart genuinely redraws from a different grouping.
    """
    return html.Div([
        html.Div([
            html.H2("How revenue breaks down"),
            html.Label("Group revenue by", style={"fontSize": "13px", "color": MUTED}),
            dcc.Dropdown(
                id="revenue-dimension",
                options=[
                    {"label": "Customer segment", "value": "revenue_by_segment"},
                    {"label": "Region", "value": "revenue_by_region"},
                    {"label": "Industry", "value": "revenue_by_industry"},
                ],
                value="revenue_by_segment",     # a default, so the page is never blank
                clearable=False,
                style={"marginTop": "6px", "maxWidth": "360px"},
            ),
        ], style=CARD),
        html.Div([dcc.Graph(id="revenue-chart")], style=CARD),
        html.Div([dcc.Graph(id="revenue-per-customer")], style=CARD),
    ])


# ============================================================================
# TAB 3 — CHURN RISK
# ============================================================================

def confusion_at(threshold):
    """Recompute the confusion matrix at any threshold, with no ML library.

    WHY THIS IS POSSIBLE WITHOUT SCIKIT-LEARN
    The probabilities are already computed and stored. Deciding which ones cross
    a threshold is a comparison, and counting the four outcomes is a loop. That
    is the whole calculation — no model, no fitting, no library.

    Returns a dictionary of counts, rates and the expected cost under the
    assumptions stored in the results file.
    """
    true_positives = false_positives = false_negatives = true_negatives = 0

    for row in DASH["customers"]:
        flagged = row["churn_probability"] >= threshold
        churned = row["actual_churn"] == 1
        if flagged and churned:
            true_positives += 1
        elif flagged and not churned:
            false_positives += 1
        elif not flagged and churned:
            false_negatives += 1
        else:
            true_negatives += 1

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0

    # * The cost of getting it wrong, which is what turns a threshold from a
    # * statistical setting into a decision. A missed churner is a lost account;
    # * a false alarm is one phone call.
    expected_cost = (false_negatives * COST["missed_churner"]
                     + false_positives * COST["false_alarm"])

    return {
        "tp": true_positives, "fp": false_positives,
        "fn": false_negatives, "tn": true_negatives,
        "precision": precision, "recall": recall,
        "flagged": true_positives + false_positives,
        "cost": expected_cost,
    }


def churn_tab():
    """A threshold slider that rewrites the numbers and the call list live.

    This is the tab the whole project is arguing for. Every library defaults to
    0.50; the slider lets a reader see for themselves what that default costs.
    """
    stats = confusion_at(0.50)

    return html.Div([
        html.Div([
            html.H2("Where to draw the line"),
            html.P(
                "A missed churner is a lost account. A false alarm is one phone call. "
                f"These numbers assume ${COST['missed_churner']:,.0f} and "
                f"${COST['false_alarm']:,.0f} respectively.",
                style={"fontSize": "13px", "color": MUTED, "marginTop": 0}),
            html.Label("Flag a customer when the predicted churn probability exceeds:",
                       style={"fontSize": "13px"}),
            dcc.Slider(
                id="churn-threshold",
                min=0.10, max=0.90, step=0.05, value=0.50,
                marks={round(value, 2): f"{value:.2f}" for value in
                       [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style=CARD),
        html.Div(id="threshold-summary", style=CARD),
        html.Div([
            html.H2("The call list — highest risk first"),
            html.P("Top 25 of 200 customers. The full list is in reports/results.json.",
                   style={"fontSize": "13px", "color": MUTED, "marginTop": 0}),
            html.Div(id="risk-table"),
        ], style=CARD),
    ])


# ============================================================================
# TAB 4 — SEGMENTS
# ============================================================================

def segments_tab():
    """What the clustering found — and, more importantly, what it did not.

    The verdict text sits above the charts on purpose. A scatter plot with
    coloured groups looks like a discovery; without the caveat in front of it,
    that is exactly what a reader would take away.
    """
    verdict = RESULTS["modelling"]["clustering"]["verdict"]
    search = RESULTS["modelling"]["clustering"]["kmeans_search"]
    density = RESULTS["modelling"]["clustering"]["density_based"]
    stability = RESULTS["modelling"]["clustering"]["stability"]

    disclaimer = html.Div([
        html.H2("Read this before the charts"),
        html.P(verdict, style={"fontSize": "13.5px", "lineHeight": "1.6", "marginTop": 0}),
        html.Ul([
            html.Li(f"KMeans best silhouette {search['best_silhouette']:.3f} at "
                    f"k={search['best_k_by_silhouette']} — {search['verdict']}"),
            html.Li(f"HDBSCAN labelled {density['hdbscan']['noise_share']:.0%} of customers as noise"),
            html.Li(f"Stability across ten random seeds: "
                    f"ARI {stability['mean_adjusted_rand_index']:.3f} — {stability['verdict']}"),
        ], style={"fontSize": "13px", "color": MUTED, "lineHeight": "1.7"}),
    ], style={**CARD, "borderLeft": f"4px solid {ACCENT}"})

    return html.Div([
        disclaimer,
        html.Div([dcc.Graph(id="segment-scatter")], style=CARD),
        html.Div([dcc.Graph(id="segment-profile")], style=CARD),
    ])


# ============================================================================
# TAB 5 — DATA AND MODELS
# ============================================================================

def quality_tab():
    """What was wrong with the data, what was done about it, and how the models scored.

    The defect inventory goes first because it is the part a sceptical reader
    should want to see: everything downstream is only as good as these repairs.
    """
    repair_rows = [
        [item["defect"], item["rows"], item.get("scope", "fact rows"),
         item["action"], item["why"]]
        for item in REPAIRS
    ]

    invoice = RESULTS["invoice_reconciliation"]
    regression = RESULTS["modelling"]["regression"]
    classification = RESULTS["modelling"]["classification"]

    model_rows = [
        [row["model"], f"{row['roc_auc_mean']:.3f}", f"{row['roc_auc_std']:.3f}",
         f"{row['accuracy_mean']:.3f}"]
        for row in classification["model_comparison"]["results"]
    ]

    prediction_rows = [
        [row["model"], f"{row['mean_r2']:+.4f}", f"{row['std_r2']:.4f}"]
        for row in regression["prediction"]["results"]
    ]

    return html.Div([
        html.Div([
            html.H2("Data quality — every repair, and why"),
            html.P(f"{len(REPAIRS)} deliberate defects were injected into this dataset so that "
                   "cleaning would have real work to do. Each repair is logged with its size and "
                   "reasoning. A repair that cannot be described is one nobody should trust.",
                   style={"fontSize": "13px", "color": MUTED}),
            simple_table(["Defect", "Rows", "Scope", "Action taken", "Why it matters"],
                         repair_rows),
        ], style=CARD),
        html.Div([
            html.H2("Invoice reconciliation"),
            html.P("The one relationship in this data with an exact expected answer: "
                   "mrr = seats × list price × (1 − discount).",
                   style={"fontSize": "13px", "color": MUTED}),
            simple_table(["Check", "Result"], [
                ["Rows checked", f"{invoice['rows_checked']:,}"],
                ["Reconcile within 5%", f"{invoice['within_5_percent']:,} "
                                        f"({invoice['match_rate']:.1%})"],
                ["Median difference", f"{invoice['median_percent_difference']:.2f}%"],
                ["Tolerance chosen", invoice["tolerance_note"]],
            ]),
        ], style=CARD),
        html.Div([
            html.H2("Churn models — cross-validated ROC-AUC"),
            simple_table(["Model", "ROC-AUC", "SD", "Accuracy"], model_rows),
            html.P(classification["model_comparison"]["note"],
                   style={"fontSize": "12px", "color": MUTED, "marginBottom": 0}),
        ], style=CARD),
        html.Div([
            html.H2("Revenue model — out-of-sample R²"),
            simple_table(["Model", "Mean R²", "SD across folds"], prediction_rows),
            html.P(regression["prediction"]["interpretation"],
                   style={"fontSize": "12px", "color": MUTED, "marginBottom": 0}),
        ], style=CARD),
    ])


# ============================================================================
# LAYOUT
# ============================================================================

APP_TITLE = "SaaS revenue analytics — Northwind Analytics"

app = dash.Dash(__name__, title=APP_TITLE)

# A Dash application is a thin layer on top of a standard Flask application, and
# `app.server` is that inner Flask object. Naming it here lets a production process
# manager import the app directly as `dashboard:server` (gunicorn does exactly that
# inside the Docker image) instead of being handed the single-threaded dev server.
server = app.server

app.layout = html.Div([
    html.Div([
        html.H1("Northwind Analytics", style={"fontSize": "24px", "margin": "0 0 4px 0"}),
        html.P("Synthetic B2B SaaS subscription data · 200 customers · 4 months · "
               f"seed {RESULTS['seed']}",
               style={"color": MUTED, "margin": 0, "fontSize": "13.5px"}),
    ], style={"marginBottom": "20px"}),

    dcc.Tabs(id="tabs", value="executive", children=[
        dcc.Tab(label="Executive", value="executive"),
        dcc.Tab(label="Revenue", value="revenue"),
        dcc.Tab(label="Churn risk", value="churn"),
        dcc.Tab(label="Segments", value="segments"),
        dcc.Tab(label="Data & models", value="quality"),
    ]),

    html.Div(id="tab-content", style={"marginTop": "18px"}),
], style=PAGE)


# ============================================================================
# CALLBACKS
# ============================================================================
# Each one follows the same shape the certification teaches:
#   @app.callback(Output(...), Input(...))
#   def handler(input_value):
#       ...
#       return something
#
# The decorator is what connects a control to a function. Nothing calls the
# handler directly — Dash does, whenever an Input changes.

@app.callback(Output("tab-content", "children"), Input("tabs", "value"))
def render_tab(tab):
    """Show the selected tab's content.

    A dictionary lookup rather than a chain of if/elif. Adding a tab means
    adding one line here instead of editing a growing conditional.
    """
    return {
        "executive": executive_tab,
        "revenue": revenue_tab,
        "churn": churn_tab,
        "segments": segments_tab,
        "quality": quality_tab,
    }[tab]()


@app.callback(Output("revenue-chart", "figure"), Input("revenue-dimension", "value"))
def update_revenue_chart(dimension):
    """Redraw the revenue bar chart for the grouping the user picked."""
    rows = DASH[dimension]
    return {
        "data": [{
            "x": [row["mrr"] for row in rows],
            "y": [row["category"] for row in rows],
            "type": "bar", "orientation": "h",
            "marker": {"color": BRAND},
            "hovertemplate": "%{y}<br>$%{x:,.0f}<extra></extra>",
        }],
        "layout": {**PLOT_LAYOUT, "title": "Revenue by " + dimension.replace("revenue_by_", ""),
                   "xaxis": {"title": "MRR (USD)"}, "yaxis": {"autorange": "reversed"},
                   "height": 420},
    }


@app.callback(Output("revenue-per-customer", "figure"), Input("revenue-dimension", "value"))
def update_revenue_per_customer(dimension):
    """Average revenue per customer for the same grouping.

    Total MRR alone conflates two different things: a category can be large
    because it has many customers or because each one pays a lot. Showing the
    average beside the total separates them, and the two charts answer different
    questions about the same dropdown selection.
    """
    rows = DASH[dimension]
    return {
        "data": [{
            "x": [row["mean_mrr"] for row in rows],
            "y": [row["category"] for row in rows],
            "type": "bar", "orientation": "h",
            "marker": {"color": GREEN},
            "text": [f"{row['customers']} customers" for row in rows],
            "textposition": "outside",
            "hovertemplate": "%{y}<br>mean $%{x:,.0f}<extra></extra>",
        }],
        "layout": {**PLOT_LAYOUT, "title": "Average revenue per customer",
                   "xaxis": {"title": "Mean MRR (USD)"}, "yaxis": {"autorange": "reversed"},
                   "height": 420},
    }


@app.callback(
    Output("threshold-summary", "children"),
    Output("risk-table", "children"),
    Input("churn-threshold", "value"),
)
def update_threshold(threshold):
    """Recount the confusion matrix and rebuild the call list at a new threshold.

    TWO OUTPUTS FROM ONE CALLBACK
    Dash allows it, and it matters here: the summary numbers and the table must
    agree. Recomputing them separately would risk showing a table that does not
    match the counts above it.
    """
    stats = confusion_at(threshold)

    summary = html.Div([
        html.H2(f"At a threshold of {threshold:.2f}"),
        html.Div([
            kpi("Churners caught", f"{stats['recall']:.0%}",
                f"{stats['tp']} of {stats['tp'] + stats['fn']}"),
            kpi("Missed", f"{stats['fn']}", "lost accounts"),
            kpi("False alarms", f"{stats['fp']}", "calls that were not needed"),
            kpi("Precision", f"{stats['precision']:.0%}", "of flags were right"),
            kpi("Expected cost", f"${stats['cost']:,.0f}",
                f"on {len(DASH['customers'])} customers"),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": "18px"}),
    ])

    # * Only customers above the threshold are listed: the table IS the call
    # * list, and an unflagged customer has no call to make.
    flagged = [row for row in DASH["customers"] if row["churn_probability"] >= threshold][:25]
    rows = [
        [row["company"], row["segment"], row["region"], f"{row['seats']:,.0f}",
         f"${row['mrr']:,.0f}", f"{row['usage_per_seat']:.1f}", f"{row['nps_score']:.0f}",
         f"{row['churn_probability']:.0%}",
         "left" if row["actual_churn"] == 1 else "stayed"]
        for row in flagged
    ]

    if not rows:
        table = html.P("No customer scores above this threshold.",
                       style={"color": MUTED, "fontSize": "13px"})
    else:
        table = simple_table(
            ["Company", "Segment", "Region", "Seats", "MRR", "Usage/seat", "NPS",
             "Churn prob.", "Outcome"], rows)

    return summary, table


# * The segments tab has no dropdown of its own: there are only two clusters and
# * both fit on screen. A control that selects between two things the reader can
# * already see would add a click and no information.

@app.callback(Output("segment-scatter", "figure"), Input("tabs", "value"))
def draw_segment_scatter(_tab):
    """Usage against sentiment, coloured by the discovered cluster.

    Rebuilt when the tab is opened rather than on every threshold change, which
    is why it subscribes to the tab value. The guard returns nothing when a
    different tab is active, so the work is skipped entirely.
    """
    if _tab != "segments":
        return no_update

    # * A set comprehension collects the distinct cluster ids; sorted() makes
    # * the order stable, so the legend does not reshuffle between releases.
    clusters = sorted({customer["cluster"] for customer in CUSTOMERS})

    traces = []
    for index, cluster in enumerate(clusters):
        # * One list comprehension instead of a DataFrame boolean mask. For 200
        # * rows the difference in speed is irrelevant and the difference in
        # * bundle size is 64 MB.
        subset = [customer for customer in CUSTOMERS if customer["cluster"] == cluster]
        traces.append({
            "x": [customer["usage_per_seat"] for customer in subset],
            "y": [customer["nps_score"] for customer in subset],
            "text": [customer["company"] for customer in subset],
            "mode": "markers", "type": "scatter", "name": f"cluster {cluster}",
            "marker": {"size": 9, "opacity": 0.75,
                       "color": [BRAND, ACCENT, GREEN, "#7B6D8D"][index % 4]},
            "hovertemplate": "%{text}<br>usage/seat %{x:.1f}<br>NPS %{y:.0f}<extra></extra>",
        })

    return {
        "data": traces,
        "layout": {**PLOT_LAYOUT,
                   "title": "Every customer: engagement against sentiment",
                   "xaxis": {"title": "Usage events per seat"},
                   "yaxis": {"title": "NPS"},
                   "height": 460},
    }


@app.callback(Output("segment-profile", "figure"), Input("tabs", "value"))
def draw_segment_profile(_tab):
    """What distinguishes the clusters from one another."""
    if _tab != "segments":
        return no_update

    summary = DASH["cluster_summary"]
    return {
        "data": [
            {"x": [row["mean_usage_per_seat"] for row in summary],
             "y": [f"cluster {row['cluster']}" for row in summary],
             "type": "bar", "orientation": "h", "name": "Usage per seat",
             "marker": {"color": BRAND}},
            {"x": [row["mean_nps"] for row in summary],
             "y": [f"cluster {row['cluster']}" for row in summary],
             "type": "bar", "orientation": "h", "name": "NPS",
             "marker": {"color": ACCENT}},
        ],
        "layout": {**PLOT_LAYOUT, "barmode": "group",
                   "title": "What makes the clusters different",
                   "xaxis": {"title": "Value"}, "height": 320},
    }


# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":
    # * debug=False: the reloader would restart the server on every file save,
    # * which is useful while editing and actively unhelpful in a demonstration.
    # * The port is read from the environment so that a hosting platform can dictate it;
    # * with no such variable set — the normal local case — it falls back to 8050.
    port = int(os.environ.get("PORT", "8050"))
    print(f"Dashboard starting on http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    app.run(debug=False, port=port)
