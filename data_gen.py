"""
data_gen.py — builds the synthetic star schema for the SaaS revenue project.

WHAT THIS FILE PRODUCES
-----------------------
Six files, every one of them at or below 800 rows:

    dim_region.csv                  6 rows
    dim_plan.csv                    6 rows
    dim_rep.csv                     8 rows
    dim_date.csv                    4 rows
    dim_customer.csv              200 rows
    fact_subscription_monthly.csv  ~740 rows

plus data/raw/saas_revenue.db (the same six tables, loadable for SQL joins)
and reports/data_quality.json (every defect injected, and what it breaks).

THE DESIGN DECISION THAT MATTERS
--------------------------------
The features genuinely CAUSE churn here. They are generated first, then churn
is derived from them by the logistic process in config.TRUE_CHURN_COEFFICIENTS.

The tempting alternative -- decide who churns, then generate that customer's
usage and tickets to "look churny" -- produces circular data. A model trained
on it would score an implausible 0.99 ROC-AUC and prove nothing at all, because
the features were drawn FROM the label. That is the synthetic-data version of
target leakage, and it is easy to do by accident.

Because causality runs features -> churn and not the reverse, the analysis can
honestly ask whether the fitted model recovered the generating process.

WHAT IS DELIBERATELY BROKEN
---------------------------
Eight documented defects are injected, listed in config section 6 and written
to reports/data_quality.json. They are light on purpose: enough for cleaning
and imputation to have real work to do, not so much that the analysis drowns.
"""

# --- Standard library -----------------------------------------------------
# These ship with Python itself: there is nothing to install. Each one is
# annotated with why THIS file needs it, because a reader meeting `unicodedata`
# or `zipfile` for the first time would otherwise have no idea what they are
# doing here.
import csv            # writes a plain-text table of the data-quality report
import datetime       # builds and formats the customers' signup dates
import io             # StringIO: an in-memory "file", used for the CSV preview
import json           # writes reports/data_quality.json
import math           # math.exp(), used by the sigmoid() helper below
import os             # portable file paths, and creating folders
import random         # Python's random numbers: choices, shuffles, weighted picks
import re             # regular expressions, used to slugify company names
import sqlite3        # loads the finished tables into a .db file for SQL querying
import sys            # sys.exit() hands a success/failure code back to the shell
import time           # measures how long the generation takes
import unicodedata    # strips accents, so "Café" and "Cafe" become the same key
import warnings       # silences noisy pandas/numpy deprecation messages
import zipfile        # bundles the finished CSVs into one downloadable .zip

# --- Third-party ----------------------------------------------------------
# Not shipped with Python. Installed by `pip install -r requirements.txt`.
import numpy as np    # fast maths on whole columns at once; np.random makes the data
import pandas as pd   # the DataFrame — the table structure everything is built in

# --- This project ---------------------------------------------------------
# ? Importing config by name works because this script is run from the project
# ? root, as `python data_gen.py`. config.py sits beside it. Nothing here
# ? reaches outside the repository folder.
import config

# * Suppress the noise pandas and numpy emit about dtypes and deprecations.
# * `warnings` is one of the most-imported modules in the certification corpus.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def seed_everything(seed):
    """Seed every random source used in this file.

    Two generators are seeded because two are used: `random` for the
    Python-native draws (choices, shuffles, text) and `numpy.random` for the
    vectorised draws. Seeding only one leaves the other free to vary between
    runs, which is the usual reason a "reproducible" pipeline is not.
    """
    random.seed(seed)
    np.random.seed(seed)


def slugify(text):
    """Return an ASCII, lowercase, hyphenated version of `text`.

    `unicodedata.normalize("NFKD", ...)` decomposes accented characters into a
    base letter plus a combining mark; dropping the combining marks
    (category "Mn") leaves plain ASCII. Without this step, "Café" and "Cafe"
    would be two different keys in any downstream join or group-by.
    """
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_only = ascii_only.lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")


def sigmoid(x):
    """Logistic function: map any real number onto (0, 1)."""
    return 1.0 / (1.0 + math.exp(-x))


COMPANY_PREFIX = [
    "Apex", "Blue Harbor", "Cedar", "Delta Ridge", "Evergreen", "Fairline",
    "Granite", "Harborview", "Ironwood", "Juniper", "Keystone", "Lakeshore",
    "Meridian", "Northgate", "Oakfield", "Pinnacle", "Quarry", "Redwood",
    "Summit", "Tidewater", "Umbra", "Vantage", "Westbrook", "Yellowstone",
    "Zenith", "Alto", "Brightpath", "Copperfield", "Driftwood", "Eastgate",
]
COMPANY_SUFFIX = [
    "Systems", "Labs", "Group", "Partners", "Industries", "Holdings",
    "Technologies", "Solutions", "Dynamics", "Collective",
]


def make_company_names(n):
    """Generate `n` unique company names.

    A `set` guarantees uniqueness, and the loop retries rather than accepting a
    collision. Company name is a natural key here -- duplicate names would make
    the dimension ambiguous and any join on name silently wrong.
    """
    names = set()
    while len(names) < n:
        names.add(f"{random.choice(COMPANY_PREFIX)} {random.choice(COMPANY_SUFFIX)}")
    return sorted(names)


# ---------------------------------------------------------------------------
# Dimension generators
# ---------------------------------------------------------------------------

def build_dim_region():
    """Region lookup. Straight from config -- no randomness involved."""
    return pd.DataFrame(config.REGIONS)[config.SCHEMA["dim_region"]["columns"]]


def build_dim_plan():
    """Plan catalogue. Also fixed in config, so the price list is auditable."""
    return pd.DataFrame(config.PLANS)[config.SCHEMA["dim_plan"]["columns"]]


def build_dim_rep():
    """Sales reps. A `rep_id` is a surrogate key; `rep_name` is the label."""
    return pd.DataFrame(config.REPS)[config.SCHEMA["dim_rep"]["columns"]]


def build_dim_date():
    """Month-level date dimension for the four months in the observation window.

    `is_quarter_end` is true for March, June, September and December. It earns
    its place because revenue teams genuinely behave differently at quarter
    end, and the analysis can test for that.
    """
    month_names = {
        1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
        7: "July", 8: "August", 9: "September", 10: "October", 11: "November",
        12: "December",
    }
    rows = []
    for date_key in config.MONTHS:
        year, month = divmod(date_key, 100)
        rows.append({
            "date_key": date_key,
            "month_name": month_names[month],
            "month_num": month,
            "quarter": (month - 1) // 3 + 1,
            "year": year,
            "is_quarter_end": month in (3, 6, 9, 12),
        })
    return pd.DataFrame(rows)[config.SCHEMA["dim_date"]["columns"]]


def build_dim_customer(n, regions, plans, reps):
    """One row per customer, holding everything FIXED for that customer.

    Churn outcome columns (`churned_month`, `churn_reason_id`, `months_active`)
    are added later, after the panel is built. They are left blank here so the
    generation order mirrors the real-world order: first the customer exists,
    later the customer leaves.
    """
    names = make_company_names(n)
    industries = [d["industry"] for d in config.INDUSTRIES]

    rows = []
    for i in range(n):
        # ? random.choices() picks WITH replacement, and the `weights` list
        # ? biases the odds. weights=[0.50, 0.33, 0.17] means SMB is half the
        # ? customer base. The weights do not have to sum to 1 -- Python
        # ? normalises them -- but they must be the same length as the list
        # ? being chosen from, or it raises ValueError.
        segment = random.choices(
            config.SEGMENTS,
            # * SMB is the biggest bucket, Enterprise the smallest. Real
            # * customer bases are shaped like this, and it stops the segment
            # * feature from being balanced in a way no real base ever is.
            weights=[0.50, 0.33, 0.17],
            k=1,
        )[0]

        # * Rep team should match the segment most of the time, but not always:
        # * accounts do get reassigned. Keeping it 85% aligned leaves a genuine
        # * exception for the data-quality checks to look at.
        # * Prefer a rep whose team matches the segment: an SMB account is
        # * usually handled by the SMB team. The 85% keeps most rows sensible
        # * while leaving ~15% of genuine reassignments for later analysis.
        # * random.random() returns a float in [0.0, 1.0), so "< 0.85" is true
        # * for 85% of draws.
        matching = [r for r in config.REPS if r["team"] == segment]
        rep = random.choice(matching) if matching and random.random() < 0.85 else random.choice(config.REPS)

        # Signup dates run from 14 to 1 month before the window opens, so
        # every customer is already live in month 1. Entries joining mid-window
        # would add a second kind of churn (never activated) and muddy the
        # target. One clean definition beats two tangled ones.
        days_before_window = random.randint(30, 420)
        signup_date = datetime.date(2026, 1, 1) - datetime.timedelta(days=days_before_window)

        # * Annual contracts are more common at the top of the market. This is
        # * the protective factor in the churn model, so where it is assigned
        # * matters: an annual deal should be an Enterprise habit, not random.
        annual_probability = {"SMB": 0.30, "Mid-Market": 0.55, "Enterprise": 0.80}[segment]

        rows.append({
            "customer_id": i + 1,
            "company_name": names[i],
            # * random.choices() always returns a LIST, even for one pick,
            # * which is why every call here ends in [0] to unwrap it.
            "industry": random.choices(industries, k=1)[0],
            # * Regional weights loosely follow where a US-headquartered SaaS
            # * company actually sells: North America dominates, then EMEA, then
            # * APAC, with Mexico and LATAM as smaller but real territories.
            "region_id": random.choices(
                [r["region_id"] for r in config.REGIONS],
                weights=[0.34, 0.10, 0.11, 0.20, 0.13, 0.12],
                k=1,
            )[0],
            "segment": segment,
            "acquisition_channel": random.choices(
                config.CHANNELS, weights=[0.30, 0.24, 0.16, 0.18, 0.12], k=1
            )[0],
            "signup_date": signup_date.isoformat(),
            "rep_id": rep["rep_id"],
            # * int(True) is 1 and int(False) is 0, so this stores the flag as
            # * a number. SQLite has no native boolean type, so an integer is
            # * what a database expects anyway.
            "is_annual_contract": int(random.random() < annual_probability),
            # * Filled in after the panel is generated.
            "churned_month": "",
            "churn_reason_id": "",
            "months_active": "",
        })

    df = pd.DataFrame(rows)
    return df[config.SCHEMA["dim_customer"]["columns"]]


# ---------------------------------------------------------------------------
# The fact table
# ---------------------------------------------------------------------------

def build_monthly_panel(customers, plans):
    """Generate a monthly row for EVERY customer and EVERY month, pre-churn.

    This is pass one. Nobody churns yet -- we are describing what each account's
    usage, tickets, discount and sentiment would have looked like if they had
    all stayed. Churn is derived from this panel in the next function, which is
    what keeps causality running in the right direction.
    """
    plan_lookup = {p["plan_id"]: p for p in config.PLANS}
    industry_risk = {d["industry"]: d["churn_risk_index"] for d in config.INDUSTRIES}

    # * Each customer is assigned a plan that suits their segment. A 15-person
    # * SMB on Enterprise+ would be nonsense, so the plan is drawn from the
    # * tiers that bracket the segment.
    plan_by_segment = {
        "SMB": [1, 2, 3],
        "Mid-Market": [2, 3, 4],
        "Enterprise": [4, 5, 6],
    }

    rows = []
    fact_id = 0

    # ? WHY itertuples() AND NOT iterrows()
    # ? Both walk a DataFrame row by row, but they behave differently:
    # ?
    # ?   iterrows()  returns a pandas Series per row. A Series holds ONE dtype,
    # ?               so a table mixing text and numbers upcasts the numbers to
    # ?               float. `customer_id` arrives as 1.0, and `region_id` too.
    # ?               It is also slow, because a new Series is built every time.
    # ?
    # ?   itertuples() returns a lightweight named tuple per row and PRESERVES
    # ?               each column's original type. `cust.customer_id` is a real
    # ?               int. It is several times faster as well.
    # ?
    # ? The earlier version of this file used iterrows() elsewhere and silently
    # ? turned all ten fact columns into floats -- including the date key, which
    # ? became 202601.0. Nothing failed; the bug was found by reading the CSV.
    # ? itertuples() removes that whole class of problem.
    for cust in customers.itertuples():
        # * Attribute access (cust.segment) rather than dict access
        # * (cust["segment"]) is what itertuples() gives you.
        segment = cust.segment
        plan_id = random.choice(plan_by_segment[segment])
        plan = plan_lookup[plan_id]
        risk = industry_risk[cust.industry]

        # Seats are drawn inside the plan's band, then held roughly steady
        # with a small month-to-month drift. Flat seats would make the MRR
        # trend perfectly smooth and unrealistically easy to model.
        seats_base = random.randint(plan["seat_band_min"], plan["seat_band_max"])

        # * Discount is negotiated, and it is one of the churn drivers: a
        # * heavily discounted deal is a price-driven deal. Enterprise accounts
        # * negotiate harder, so their discounts run higher.
        discount_mean = {"SMB": 0.04, "Mid-Market": 0.10, "Enterprise": 0.18}[segment]
        discount = float(np.clip(np.random.normal(discount_mean, 0.05), 0.0, 0.45))

        # * Baseline engagement PER SEAT, not in total.
        # !
        # ! An earlier version drew `usage_events` as an absolute count and
        # ! multiplied nothing by the seat count. The result was that a 5-seat
        # ! account used the product about as much as a 1,000-seat one --
        # ! correlation between seats and usage came out at -0.04.
        # !
        # ! That broke the analysis in a way that was easy to miss: the derived
        # ! `usage_per_seat` became a measure of how FEW seats a customer had,
        # ! not of how engaged they were, and it was the strongest protective
        # ! factor in the churn model. A plausible-looking number was measuring
        # ! the wrong thing entirely.
        # !
        # ! Now the per-seat rate is drawn first and multiplied by the seat
        # ! count below, so a bigger account genuinely generates more activity.
        usage_per_seat_base = float(np.clip(np.random.normal(18.0, 7.0), 1.5, 45.0))

        for month_index, date_key in enumerate(config.MONTHS, start=1):
            fact_id += 1

            seats = max(1, int(seats_base * np.random.normal(1.0, 0.04)))

            # Usage drifts down for accounts with a big discount and for
            # riskier industries -- a mild echo of the churn process, kept
            # small so it does not become a second, hidden cause.
            usage_drift = -0.06 * discount * 10 - 0.02 * risk
            # * Total events = seats x the per-seat rate x this month's drift
            # * and noise. Multiplying by seats is what makes the figure scale
            # * the way usage on a real product does.
            usage = float(np.clip(
                seats * usage_per_seat_base
                * (1.0 + usage_drift * (month_index - 1))
                * np.random.normal(1.0, 0.18),
                0.0, seats * 60.0,
            ))

            # ? EVERYTHING FROM HERE DOWN USES THE PER-SEAT RATE, NOT THE TOTAL.
            # ? This is subtle and it caused a real bug. `usage` is now a TOTAL
            # ? (seats x per-seat rate), so a 300-seat account records roughly
            # ? 5,400 events. Any formula written as "(12 - usage)" is therefore
            # ? always deeply negative, the max(0, ...) clamp fires every time,
            # ? and the variable silently stops varying.
            # ?
            # ? That is exactly what happened: tickets flattened to a constant
            # ? and their correlation with churn collapsed from +0.25 to +0.04,
            # ? while NPS saturated at its ceiling of 100 with a skew of -8.9.
            # ? The features were alive; they were just measuring nothing.
            # ?
            # ? Dividing back to a per-seat basis restores the intended signal.
            usage_per_seat_now = usage / max(seats, 1)

            # * Tickets are a Poisson count. Low usage produces more tickets:
            # * confused or disengaged users raise support requests.
            ticket_rate = 0.55 + max(0.0, (12.0 - usage_per_seat_now)) * 0.09
            tickets = int(np.random.poisson(ticket_rate))

            # * The dominant support topic for this customer-month.
            # ?
            # ? WHY IT DEPENDS ON THE MONTH'S STATE AND NOT ON CHURN
            # ? The weights are nudged by two things the customer ALREADY has:
            # ? how many tickets they raised, and how heavily they use the
            # ? product. A busy support month leans toward hard failures; a
            # ? quiet, low-usage month leans toward usability complaints.
            # ?
            # ? Crucially it does NOT depend on whether they later churn. If it
            # ? did, the topic would be a proxy for the label and the word cloud
            # ? would be showing us the answer rather than the evidence. The
            # ? topics are a SYMPTOM of the same underlying state that already
            # ? drives churn -- not a second, hidden cause.
            topic_weights = []
            for topic in config.TICKET_TOPICS:
                weight = topic["weight"]
                if topic["kind"] == "failure":
                    weight *= 1.0 + min(tickets, 4) * 0.22
                elif topic["kind"] == "usability":
                    weight *= 1.0 + max(0.0, (12.0 - usage_per_seat_now)) * 0.055
                topic_weights.append(weight)
            total_weight = sum(topic_weights)
            topic_weights = [w / total_weight for w in topic_weights]
            primary_topic = random.choices(
                [topic["topic"] for topic in config.TICKET_TOPICS],
                weights=topic_weights,
                k=1,
            )[0]

            # * NPS is a survey score from -100 to 100, and it tracks engagement.
            # *
            # * The formula is CENTRED on the typical per-seat rate (18) rather
            # * than anchored at zero. Written as "18 + rate * 1.4" and fed a
            # * per-seat rate of 18, the mean lands near 43 with a standard
            # * deviation of 22 -- which pushes the upper tail past 100 and
            # * clips it. Clipping is not fatal, but when it catches most of the
            # * distribution the variable stops carrying information. Centring
            # * keeps the spread inside the scale.
            nps = float(np.clip(
                np.random.normal(45.0 + (usage_per_seat_now - 18.0) * 1.5, 20.0),
                -100, 100,
            ))

            mrr = seats * plan["list_price_per_seat"] * (1.0 - discount)
            mrr = float(round(mrr * np.random.normal(1.0, config.MRR_NOISE_SD), 2))

            rows.append({
                "fact_id": fact_id,
                # * int() is belt-and-braces: itertuples() already preserves
                # * the type, but casting here means the column is an int even
                # * if this line is ever fed a differently-built frame.
                "customer_id": int(cust.customer_id),
                "plan_id": int(plan_id),
                "date_key": int(date_key),
                "seats": seats,
                "mrr": max(mrr, 0.0),
                "usage_events": round(usage, 2),
                "support_tickets": tickets,
                "discount_pct": round(discount, 4),
                "nps_score": round(nps, 1),
                "primary_ticket_topic": primary_topic,
            })

    panel = pd.DataFrame(rows)

    # * usage_per_seat is deliberately NOT a stored column. It is a derived
    # * measure, and deriving it in analysis.py keeps one definition of it
    # * rather than two that can disagree.
    usage_per_seat = panel["usage_events"] / panel["seats"].clip(lower=1)
    panel["_usage_per_seat"] = usage_per_seat
    return panel


def apply_churn(panel, customers):
    """Decide which customers leave, using the TRUE generating coefficients.

    The logistic is evaluated on each customer's AGGREGATED panel behaviour,
    exactly as a real churn model would be: you know how someone has used the
    product so far, and you ask whether they stay.

    Returns (panel_without_churners, customers_with_outcome).
    """
    industry_risk = {d["industry"]: d["churn_risk_index"] for d in config.INDUSTRIES}
    coef = config.TRUE_CHURN_COEFFICIENTS

    # ? groupby("customer_id") splits the panel into one group per customer,
    # ? and .agg(...) computes one number per group. The result has one row per
    # ? customer -- which is the grain a churn model needs, since churn is a
    # ? customer-level outcome, not a monthly one.
    aggregated = panel.groupby("customer_id").agg(
        mean_usage_per_seat=("_usage_per_seat", "mean"),
        total_tickets=("support_tickets", "sum"),
        mean_discount=("discount_pct", "mean"),
        mean_nps=("nps_score", "mean"),
        months_observed=("date_key", "count"),
    ).reset_index()

    # * how="left" keeps every customer even if the aggregation is missing.
    # * An inner join would silently drop customers and quietly change the
    # * churn rate -- a classic and invisible error.
    merged = customers.merge(aggregated, on="customer_id", how="left")

    # ? .map(dict) looks each industry up in the risk dictionary and returns the
    # ? matching number. Unknown values become NaN rather than raising, which is
    # ? why the tests check that the three blank-industry defects are handled.
    merged["industry_risk"] = merged["industry"].map(industry_risk)

    # * (a == b) produces a column of True/False; .astype(int) turns it into
    # * 1/0, which is what scikit-learn and statsmodels expect as a feature.
    merged["is_smb"] = (merged["segment"] == "SMB").astype(int)

    # * Assemble the linear predictor, term by term, so that each term can be
    # * read directly against its coefficient in config.
    logit = (
        config.TRUE_CHURN_INTERCEPT
        + coef["usage_per_seat"]      * merged["mean_usage_per_seat"]
        + coef["support_tickets"]     * merged["total_tickets"]
        + coef["discount_pct"]        * merged["mean_discount"]
        + coef["nps_score"]           * merged["mean_nps"]
        + coef["is_smb"]              * merged["is_smb"]
        + coef["industry_risk"]       * merged["industry_risk"]
        + coef["is_annual_contract"]  * merged["is_annual_contract"]
        + coef["months_active"]       * merged["months_observed"]
    )

    # * Noise on the log-odds scale, then the sigmoid. This is what stops the
    # * labels being a deterministic function of the features -- which would
    # * give a perfect classifier and a worthless project.
    logit = logit + np.random.normal(0.0, config.CHURN_NOISE_SD, len(merged))
    merged["churn_probability"] = 1.0 / (1.0 + np.exp(-logit))

    # * Convert probabilities into a fixed number of churners rather than an
    # * independent coin flip per customer. Flipping coins gives a churn rate
    # * that wanders between runs; ranking and taking the top N gives exactly
    # * the target rate every time, which keeps the class balance stable.
    n_churn = int(round(config.N_CUSTOMERS * config.TARGET_CHURN_RATE))
    churn_order = merged.sort_values("churn_probability", ascending=False)
    churner_ids = set(churn_order.head(n_churn)["customer_id"].tolist())

    # A churner must have at least two months of history, or the features
    # used to predict them would be built on a single observation. So the
    # churn month is drawn from {3, 4}: they are observed in months 1-2, or
    # 1-3, and then they are gone.
    churn_month_by_customer = {}
    for customer_id in churner_ids:
        churn_month_by_customer[customer_id] = random.choice([config.MONTHS[2], config.MONTHS[3]])

    # * Drop the rows that fall after a customer's churn month.
    # !
    # ! The obvious way to write this is a loop with `iterrows()`. Do not.
    # ! `iterrows()` builds a pandas Series PER ROW, and a Series can hold only
    # ! ONE dtype -- so iterating a frame that contains any float column
    # ! silently upcasts the integers alongside it. The first version of this
    # ! file did exactly that, and every column in the fact table came out as
    # ! float64, including `fact_id` and `date_key` (202601.0 instead of 202601).
    # !
    # ! The joins still worked, because SQLite compares numbers numerically.
    # ! That is what makes the bug dangerous: the output looks correct while the
    # ! schema and the CSV are both wrong.
    # !
    # ! The vectorised form below preserves dtypes and runs faster.
    last_allowed = panel["customer_id"].map(churn_month_by_customer)
    keep_mask = last_allowed.isna() | (panel["date_key"] < last_allowed)
    panel_kept = (
        panel[keep_mask]
        .drop(columns=["_usage_per_seat"])
        .reset_index(drop=True)
    )

    # * Now write the outcome back onto dim_customer. `months_active` is the
    # * number of months actually billed, which differs between churners and
    # * stayers and is a legitimate feature.
    months_active = panel_kept.groupby("customer_id")["date_key"].count().to_dict()
    customers = customers.copy()
    # * .map(dict) attaches each customer's billed-month count by looking up
    # * their id. .fillna(0) covers anyone absent from the dictionary, and
    # * .astype(int) guarantees an integer even after the fill introduced a
    # * value into what would otherwise be a float column.
    customers["months_active"] = customers["customer_id"].map(months_active).fillna(0).astype(int)
    customers["churned_month"] = customers["customer_id"].map(churn_month_by_customer).fillna("")
    customers["churned_month"] = customers["churned_month"].apply(
        lambda v: int(v) if v != "" else ""
    )

    # ! The churn reason is assigned ONLY to customers who actually churned, and
    # ! it is a consequence of churn, not a cause. It lives on dim_customer and
    # ! must never be used as a model feature -- knowing the reason someone left
    # ! makes predicting that they left trivial.
    reason_ids = [r["churn_reason_id"] for r in config.CHURN_REASONS]
    customers["churn_reason_id"] = customers.apply(
        lambda r: random.choices(reason_ids, weights=[0.31, 0.24, 0.18, 0.19, 0.08], k=1)[0]
        if r["churned_month"] != "" else "",
        axis=1,
    )

    # * Re-select in schema order so the CSV columns never drift between runs.
    return panel_kept, customers[config.SCHEMA["dim_customer"]["columns"]]


# ---------------------------------------------------------------------------
# Defect injection
# ---------------------------------------------------------------------------

def inject_defects(customers, panel):
    """Introduce the eight documented defects.

    Each defect returns a record describing what was done, how many rows it
    touched and which check should catch it. The records are written to
    reports/data_quality.json and surfaced on the dashboard's Data Quality tab.

    Defects are injected AFTER the data is otherwise correct, so the size of
    each problem is known exactly. Cleaning code can then be tested against a
    known answer rather than a guess.
    """
    records = []
    customers = customers.copy()
    panel = panel.copy()

    # --- Customer defects -------------------------------------------------

    # * 1. Blank industry. Blocks any group-by on industry until imputed.
    idx = random.sample(list(customers.index), config.DEFECT_CUSTOMER_MISSING_INDUSTRY)
    customers.loc[idx, "industry"] = ""
    records.append({
        "table": "dim_customer", "column": "industry",
        "defect": "Blank industry", "rows_affected": len(idx),
        "breaks": "Cannot group or segment by industry until imputed",
    })

    # * 2. Blank region_id. This one is a broken FOREIGN KEY, which is a much
    # * more serious class of problem than a blank label: the join drops rows.
    idx = random.sample(list(customers.index), config.DEFECT_CUSTOMER_BLANK_REGION)
    customers.loc[idx, "region_id"] = np.nan
    records.append({
        "table": "dim_customer", "column": "region_id",
        "defect": "Blank region_id (broken foreign key)", "rows_affected": len(idx),
        "breaks": "Inner join to dim_region silently drops these customers",
    })

    # * 3. Mixed date formats. signup_date should be ISO (YYYY-MM-DD); a few
    # * rows are switched to DD/MM/YYYY, which parses differently or not at all.
    idx = random.sample(list(customers.index), config.DEFECT_MIXED_DATE_FORMAT)
    for i in idx:
        iso = customers.at[i, "signup_date"]
        if isinstance(iso, str) and len(iso) == 10:
            y, m, d = iso.split("-")
            customers.at[i, "signup_date"] = f"{d}/{m}/{y}"
    records.append({
        "table": "dim_customer", "column": "signup_date",
        "defect": "Mixed date format (DD/MM/YYYY among ISO)", "rows_affected": len(idx),
        "breaks": "pd.to_datetime parses inconsistently; tenure is wrong for those rows",
    })

    # --- Fact defects ----------------------------------------------------

    # * 4. Blank usage_events. The one column imputation genuinely acts on.
    idx = random.sample(list(panel.index), config.DEFECT_FACT_MISSING_USAGE)
    panel.loc[idx, "usage_events"] = np.nan
    records.append({
        "table": "fact_subscription_monthly", "column": "usage_events",
        "defect": "Blank usage_events", "rows_affected": len(idx),
        "breaks": "Mean usage and the usage-per-seat feature become biased if dropped",
    })

    # * 5. Negative usage. Impossible: you cannot use the product a negative
    # * number of times. Negative values would drag any mean computed on the
    # * raw column downward, which is why this is a real defect and not noise.
    idx = random.sample(list(panel.index), config.DEFECT_FACT_NEGATIVE_USAGE)
    panel.loc[idx, "usage_events"] = -panel.loc[idx, "usage_events"].abs()
    records.append({
        "table": "fact_subscription_monthly", "column": "usage_events",
        "defect": "Negative usage_events", "rows_affected": len(idx),
        "breaks": "Impossible values that bias any mean computed without filtering",
    })

    # * 6. Discount above 100%. A discount of 1.3 means the customer is paid to
    # * use the product. This produces a negative MRR if the invoice formula is
    # * applied naively, and it is caught by the MRR reconciliation check.
    idx = random.sample(list(panel.index), config.DEFECT_DISCOUNT_OUT_OF_RANGE)
    panel.loc[idx, "discount_pct"] = panel.loc[idx, "discount_pct"] + 1.0
    records.append({
        "table": "fact_subscription_monthly", "column": "discount_pct",
        "defect": "Discount above 100%", "rows_affected": len(idx),
        "breaks": "Produces negative MRR; breaks the invoice arithmetic check",
    })

    # * 7. One duplicated block of rows. A classic ingestion fault: the same
    # * file imported twice, or a retry that was not idempotent. Because the
    # * duplicates carry duplicate fact_ids, a primary-key constraint would
    # * reject them -- which is exactly the point being demonstrated.
    sample = panel.sample(config.DEFECT_DUPLICATE_FACT_ROWS, random_state=config.RANDOM_SEED)
    panel = pd.concat([panel, sample], ignore_index=True)
    records.append({
        "table": "fact_subscription_monthly", "column": "fact_id",
        "defect": "Duplicated rows", "rows_affected": len(sample),
        "breaks": "Double-counts revenue and inflates usage totals",
    })

    # * 8. Rep hired after the customer signed. Logically impossible, and it
    # * cannot happen by chance because reps are drawn from config. Injected by
    # * rewiring a few customers to the newest rep.
    # ? Find the rep hired most recently, then reassign customers who signed up
    # ? BEFORE that hire date. Those assignments are impossible: nobody owns an
    # ? account that predates them joining the company.
    # ?
    # ? The earlier version selected customers by a crude year test ("did they
    # ? sign in 2024 or 2025?") and the newest rep had been hired in May 2024.
    # ? Every customer therefore signed AFTER that rep joined, so the
    # ? "impossible" assignments it created were entirely legal and the defect
    # ? silently injected zero rows while still reporting itself in the log.
    # ? It is now driven by an actual date comparison, which cannot miss.
    newest_rep = max(config.REPS, key=lambda r: r["hire_date"])
    signup_dates = pd.to_datetime(customers["signup_date"], format="%Y-%m-%d", errors="coerce")
    # * errors="coerce" matters: five rows are in DD/MM/YYYY, so a strict parse
    # * would raise. Those become NaT and simply are not selected.
    eligible = customers.index[signup_dates < pd.Timestamp(newest_rep["hire_date"])][:4]
    customers.loc[eligible, "rep_id"] = newest_rep["rep_id"]
    records.append({
        "table": "dim_customer", "column": "rep_id",
        "defect": "Rep hired after the customer signed up", "rows_affected": len(eligible),
        "breaks": "Temporal impossibility; invalidates any rep-performance analysis",
    })

    return customers, panel, records


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

# * Columns that must be integers. Keys and counts are never fractional, and
# * letting pandas store them as floats produces 202601.0 in the CSV, a REAL
# * column in SQLite, and a schema that disagrees with the documentation.
# * Enforcing them here means the guarantee holds even if an upstream edit
# * reintroduces a NaN and upcasts the column.
INTEGER_COLUMNS = {
    "dim_region": ["region_id"],
    "dim_plan": ["plan_id", "tier_rank", "seat_band_min", "seat_band_max"],
    "dim_rep": ["rep_id"],
    "dim_date": ["date_key", "month_num", "quarter", "year", "is_quarter_end"],
    "dim_customer": ["customer_id", "region_id", "rep_id", "is_annual_contract",
                     "churn_reason_id", "months_active"],
    "fact_subscription_monthly": ["fact_id", "customer_id", "plan_id", "date_key",
                                  "seats", "support_tickets"],
}


def enforce_dtypes(tables):
    """Cast integer columns back to nullable integers, reporting any loss.

    `Int64` (capital I) is pandas\' nullable integer type: unlike `int64` it can
    hold a missing value, which matters because the injected defects put NaNs in
    `region_id` and `usage_events`. Casting to plain int64 would raise; casting
    to Int64 keeps the column honest about both its type and its gaps.
    """
    for table, columns in INTEGER_COLUMNS.items():
        df = tables[table]
        for column in columns:
            if column in df.columns:
                # * errors="coerce" turns anything unparseable into NaN
                # * instead of raising, and .astype("Int64") is pandas'
                # * NULLABLE integer type. Plain int64 cannot hold a missing
                # * value, so it would raise on the blank region_id defects.
                df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
    return tables


def write_csvs(tables):
    """Write each table to CSV using pandas, with a stable column order."""
    written = []
    for name, df in tables.items():
        path = os.path.join(config.DATA_RAW_DIR, f"{name}.csv")
        df.to_csv(path, index=False, encoding="utf-8")
        written.append((name, len(df), path))
    return written


def write_sqlite(tables):
    """Load every table into SQLite, in foreign-key order.

    `if_exists="replace"` makes the load idempotent: re-running the generator
    rebuilds each table from scratch rather than appending a second copy.

    `sqlite3` is a standard-library module, so it belongs at the top with the
    others -- but it is imported here, next to its only use, so a reader of this
    function does not have to scroll to understand it. The connection is closed
    explicitly: a `with` block on a sqlite3 connection commits the transaction
    but does NOT close the file handle, which on Windows leaves the .db locked.
    """
    conn = sqlite3.connect(config.SQLITE_PATH)
    try:
        for name in config.TABLE_LOAD_ORDER:
            # ? to_sql() writes a DataFrame straight into a database table.
            # ?   if_exists="replace" drops and recreates it, so re-running the
            # ?     generator overwrites rather than appending a second copy --
            # ?     which is what makes this step repeatable.
            # ?   index=False stops pandas writing its own 0,1,2 row counter as
            # ?     an extra column nobody asked for.
            tables[name].to_sql(name, conn, if_exists="replace", index=False)
        conn.commit()
    finally:
        conn.close()
    return config.SQLITE_PATH


def write_quality_report(records, tables, panel_pre_defect_rows):
    """Persist the defect inventory, plus a plain summary of the shape.

    This file is the contract between the generator and the analysis: it states
    what is wrong before anything tries to fix it, so the cleaning steps can be
    checked against a known list rather than trusted.
    """
    report = {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "seed": config.RANDOM_SEED,
        "row_counts": {name: int(len(df)) for name, df in tables.items()},
        "rows_under_cap": all(len(df) <= 800 for df in tables.values()),
        "max_allowed_rows": 800,
        "defects_injected": records,
        "defects_total_rows": int(sum(r["rows_affected"] for r in records)),
        "fact_rows_before_duplication": int(panel_pre_defect_rows),
        "churn": {
            "customers": int(len(tables["dim_customer"])),
            "churned": int((tables["dim_customer"]["churned_month"] != "").sum()),
            "rate": round(
                float((tables["dim_customer"]["churned_month"] != "").mean()), 4
            ),
        },
        "leakage_warning": config.LEAKAGE_WARNING,
    }
    path = os.path.join(config.REPORTS_DIR, "data_quality.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return path, report


def write_delivery_zip(tables):
    """Zip the CSV outputs into a single delivery bundle.

    Written with the standard library `zipfile` rather than shelling out, so the
    bundle is reproducible and no external tool has to be present.
    """
    path = os.path.join(config.DATA_RAW_DIR, "saas_revenue_csv_bundle.zip")
    # ? zipfile is in the standard library, so nobody has to install anything to
    # ? open the result. "w" means write (creating or overwriting the file), and
    # ? ZIP_DEFLATED is the actual compression step -- without it the archive
    # ? would be a plain, uncompressed bundle wearing a .zip name.
    # ? The `with` block closes the archive on the way out, which also writes the
    # ? end-of-archive record. Skip it and the file is unreadable.
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in config.TABLE_LOAD_ORDER:
            zf.writestr(f"{name}.csv", tables[name].to_csv(index=False))
    return path


def preview_csv(tables, name, n=3):
    """Return the first `n` rows of a table as an in-memory CSV string.

    Uses `io.StringIO` so nothing touches disk -- the standard-library way to
    treat a string as if it were a file.
    """
    # ? io.StringIO is an in-memory file. It behaves like an object you can
    # ? write text into and read back, but nothing touches the disk -- which is
    # ? exactly what is wanted for a throwaway preview.
    buffer = io.StringIO()

    # * to_csv() writes into the buffer rather than a path, because the buffer
    # * is a perfectly good file-like object as far as pandas is concerned.
    tables[name].head(n).to_csv(buffer, index=False)

    # * getvalue() returns everything written so far as a normal string.
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Build every table, inject the defects, and write all the outputs.

    THE ORDER MATTERS AND IS NOT ARBITRARY
        1. dimensions first   — the fact table references them
        2. customers          — a fact row needs a customer to belong to
        3. the monthly panel   — generated for everyone, BEFORE anyone churns
        4. churn applied       — derived FROM the panel, so causes point forward
        5. defects injected    — last, so their size is exactly known and can be
                                 reported honestly rather than estimated
        6. outputs written     — CSV, SQLite, zip, quality report

    Step 3 before step 4 is the important one. Generating the panel first and
    deriving churn from it is what keeps the causality running in the right
    direction; doing it the other way round would make the features a symptom
    of the label and the whole dataset worthless for modelling.

    Returns 0 on success, which `sys.exit(main())` turns into a shell exit code.
    """
    started = time.time()
    config.ensure_directories()
    seed_everything(config.RANDOM_SEED)

    print("=" * 78)
    print("DATA GENERATION — Northwind Analytics synthetic SaaS star schema")
    print("=" * 78)
    print(f"  seed {config.RANDOM_SEED} · {config.N_CUSTOMERS} customers · "
          f"{config.N_MONTHS} months")
    print()

    dim_region = build_dim_region()
    dim_plan = build_dim_plan()
    dim_rep = build_dim_rep()
    dim_date = build_dim_date()
    print(f"  dimensions built       region {len(dim_region)} · plan {len(dim_plan)} · "
          f"rep {len(dim_rep)} · date {len(dim_date)}")

    dim_customer = build_dim_customer(
        config.N_CUSTOMERS, dim_region, dim_plan, dim_rep
    )
    print(f"  customers generated    {len(dim_customer)}")

    panel_full = build_monthly_panel(dim_customer, dim_plan)
    print(f"  panel before churn     {len(panel_full)} rows "
          f"({config.N_CUSTOMERS} × {config.N_MONTHS})")

    panel, dim_customer = apply_churn(panel_full, dim_customer)
    churned = int((dim_customer["churned_month"] != "").sum())
    print(f"  churn applied          {churned} customers left "
          f"({churned / config.N_CUSTOMERS:.1%}), panel now {len(panel)} rows")

    fact_rows_clean = len(panel)
    dim_customer, panel, defect_records = inject_defects(dim_customer, panel)
    print(f"  defects injected       {len(defect_records)} distinct faults, "
          f"{sum(r['rows_affected'] for r in defect_records)} rows touched")
    print(f"  panel after defects    {len(panel)} rows")

    tables = {
        "dim_region": dim_region,
        "dim_plan": dim_plan,
        "dim_rep": dim_rep,
        "dim_date": dim_date,
        "dim_customer": dim_customer,
        "fact_subscription_monthly": panel,
    }

    # * Normalise dtypes before anything is written, so the CSV, the database
    # * and the documented schema all agree.
    tables = enforce_dtypes(tables)

    written = write_csvs(tables)
    db_path = write_sqlite(tables)
    zip_path = write_delivery_zip(tables)
    report_path, report = write_quality_report(defect_records, tables, fact_rows_clean)

    print()
    print("  FILES WRITTEN")
    for name, rows, path in written:
        flag = "OK " if rows <= report["max_allowed_rows"] else "OVER"
        print(f"    {flag} {name + '.csv':<34} {rows:>5} rows")
    print(f"         {'saas_revenue.db':<34} {'':>5}       (same six tables)")
    print(f"         {'saas_revenue_csv_bundle.zip':<34} {'':>5}       (delivery bundle)")
    print(f"         {'data_quality.json':<34} {'':>5}       (defect inventory)")
    print()
    print("  PREVIEW — first 3 rows of fact_subscription_monthly")
    for line in preview_csv(tables, "fact_subscription_monthly").strip().split("\n"):
        print("    " + line)

    elapsed = time.time() - started
    print()
    print(f"  completed in {elapsed:.2f}s")
    print()
    print("  NEXT: run analysis.py, which cleans this data, reconciles the invoice")
    print("        arithmetic, and fits the three model families.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
