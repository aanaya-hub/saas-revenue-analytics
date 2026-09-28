"""
main.py — run the whole project from one command.

WHAT THIS FILE IS FOR
    python main.py              build the data, then analyse it
    python main.py --serve      the above, then start the dashboard
    python main.py --skip-generate
    python main.py --help

Everything it runs could be run by hand, and the Makefile does exactly that.
This exists because a reader arriving at the repository should be able to get
from a clean clone to a running analysis without reading four files first.

WHY IT USES subprocess RATHER THAN IMPORTING THE MODULES
Importing data_gen and analysis directly would be fewer lines and would let them
share memory. It is also the wrong thing to do here, for three reasons:

  1. ISOLATION. A crash inside pandas leaves its state behind in the process
     that survives it. Running each step in its own interpreter means a failure
     cannot contaminate the next step.
  2. HONEST FAILURE. Each step gets its own exit code, so "analysis failed
     because the data was never built" is distinguishable from "the analysis
     itself threw". Imported modules would collapse both into one traceback.
  3. IT MIRRORS REALITY. This is how the pipeline actually runs in the Makefile
     and how it would run in a scheduler. A main.py that quietly does something
     different from the documented commands is a trap for the next reader.

WHY sys.executable AND NOT "python"
    `python` on the PATH may be a different interpreter from the one running
    this file — a system Python rather than the venv. Using sys.executable
    guarantees the sub-steps run in the same environment as the orchestrator,
    which is what a reader expects and what a venv quietly breaks if you forget.
"""

import os
import subprocess
import sys
import time

# ============================================================================
# Configuration
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# * The pipeline, in order. Each entry is (label, filename, what it does), so
# * the progress output can explain itself without a separate lookup table.
STEPS = [
    ("generate", "data_gen.py",
     "build the synthetic star schema (CSV, SQLite, zip)"),
    ("analyse", "analysis.py",
     "clean, model, and write reports/results.json + 22 figures"),
]

SERVE_STEP = ("serve", "dashboard.py", "start the dashboard at http://127.0.0.1:8050")

FLAG_HELP = "--help"
FLAG_SERVE = "--serve"
FLAG_SKIP_GENERATE = "--skip-generate"
FLAG_SKIP_ANALYSE = "--skip-analyse"


# ============================================================================
# Argument handling
# ============================================================================
# ? WHY NOT argparse
# ? argparse is in the standard library and would be the obvious choice. It is
# ? also not among the sixteen standard-library modules the certification's
# ? artefacts import, and this project deliberately stays inside that set. Four
# ? flags do not need a parser framework; a loop over sys.argv is readable and
# ? leaves no behaviour hidden behind a library.

def parse_flags(argv):
    """Turn command-line arguments into a dictionary of booleans.

    Returns None if an argument is not recognised, so the caller can print the
    help text rather than silently ignoring a typo. Silently ignoring
    `--skip-generat` would run the generator the user was trying to skip.
    """
    flags = {
        "help": False,
        "serve": False,
        "skip_generate": False,
        "skip_analyse": False,
    }
    for argument in argv:
        if argument in ("-h", FLAG_HELP):
            flags["help"] = True
        elif argument in ("-s", FLAG_SERVE):
            flags["serve"] = True
        elif argument == FLAG_SKIP_GENERATE:
            flags["skip_generate"] = True
        elif argument == FLAG_SKIP_ANALYSE:
            flags["skip_analyse"] = True
        else:
            return None          # unknown flag — the caller shows help
    return flags


def print_help():
    """Explain every flag, so --help is genuinely useful."""
    print(__doc__.strip())
    print()
    print("Steps, in order:")
    for label, script, purpose in STEPS:
        print(f"  {label:<10} {script:<16} {purpose}")
    print(f"  {SERVE_STEP[0]:<10} {SERVE_STEP[1]:<16} {SERVE_STEP[2]} (only with --serve)")
    print()
    print("The dashboard reads reports/results.json, so analyse must have run")
    print("at least once before serve will work.")


# ============================================================================
# Running a step
# ============================================================================

def run_step(label, script, purpose):
    """Run one script as a child process and report how it went.

    Returns True on success. The child's output streams straight to the
    terminal rather than being captured: a reader watching a two-minute analysis
    wants to see progress, and swallowing it to print back afterwards would make
    the run look frozen.
    """
    path = os.path.join(BASE_DIR, script)
    if not os.path.exists(path):
        print(f"  [skip] {label:<10} {script} not found")
        return False

    print()
    print("-" * 74)
    print(f"  {label.upper()}  —  {purpose}")
    print("-" * 74)

    started = time.time()
    # * check=False so a non-zero exit is reported by US rather than raised as
    # * an exception mid-pipeline. We want to name the step that failed.
    result = subprocess.run([sys.executable, path], cwd=BASE_DIR, check=False)
    elapsed = time.time() - started

    if result.returncode == 0:
        print(f"\n  {label} finished in {elapsed:.1f}s")
        return True

    print(f"\n  {label} FAILED after {elapsed:.1f}s (exit code {result.returncode})")
    return False


def check_results_exist():
    """Report whether the dashboard has anything to read.

    Cheap check, and it catches the most likely confusion: running `--serve`
    on a clean clone where the analysis has never run. The dashboard refuses to
    start in that case, but saying so here puts the explanation next to the
    command that caused it.
    """
    results = os.path.join(BASE_DIR, "reports", "results.json")
    if os.path.exists(results):
        size = os.path.getsize(results)
        print(f"  reports/results.json present ({size:,} bytes)")
        return True
    print("  reports/results.json is MISSING — the dashboard has nothing to show")
    return False


# ============================================================================
# Main
# ============================================================================

def main(argv):
    """Run the requested steps in order and return a shell exit code.

    Returns
    -------
    0   everything asked for succeeded
    1   a step failed, or the dashboard was requested with no results to show
    2   an unrecognised argument was passed

    The three codes matter because `make` and any CI runner read the exit code,
    not the printed text. Returning 0 after a failure would report success to an
    automated caller that never saw the output.
    """
    flags = parse_flags(argv)
    if flags is None or flags["help"]:
        print_help()
        # * An unrecognised flag is an error; --help is not.
        return 0 if flags else 2

    print("=" * 74)
    print("  SaaS revenue analytics — Northwind Analytics")
    print("  synthetic B2B subscription data, end to end")
    print("=" * 74)

    started = time.time()
    completed = []

    # --- generate -----------------------------------------------------------
    # * Skipped rather than re-run when explicitly asked: generation is
    # * deterministic, so re-running is harmless but wastes a few seconds, and
    # * skipping is what a reader wants when iterating on the analysis.
    if flags["skip_generate"]:
        print("\n  generate  skipped (--skip-generate)")
    else:
        if not run_step(*STEPS[0]):
            return 1
        completed.append("generate")

    # --- analyse ------------------------------------------------------------
    if flags["skip_analyse"]:
        print("\n  analyse   skipped (--skip-analyse)")
    else:
        if not run_step(*STEPS[1]):
            return 1
        completed.append("analyse")

    # --- serve --------------------------------------------------------------
    # * The dashboard blocks until Ctrl+C, so it is deliberately not included in
    # * the timing summary below — a run that ends when the user stops watching
    # * has no meaningful duration.
    if flags["serve"]:
        print()
        print("-" * 74)
        if not check_results_exist():
            return 1
        print()
        print("  Starting the dashboard. Open http://127.0.0.1:8050")
        print("  Press Ctrl+C to stop.")
        print("-" * 74)
        # * check=False: Ctrl+C is the intended way to stop this, and it arrives
        # * as a non-zero exit code that is not a failure.
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "dashboard.py")],
                       cwd=BASE_DIR, check=False)
        return 0

    # --- summary ------------------------------------------------------------
    elapsed = time.time() - started
    print()
    print("=" * 74)
    print(f"  Completed {len(completed)} step(s) in {elapsed:.1f}s: {', '.join(completed)}")
    print()
    print("  Produced:")
    print("    data/raw/              6 CSVs, saas_revenue.db, a zip bundle")
    print("    reports/results.json   every number the dashboard reads")
    print("    reports/data_quality.json   the defect inventory")
    print("    reports/figures/       22 PNGs")
    print()
    print("  Next:  python main.py --serve     (or `make serve`)")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    # * sys.exit(main(...)) turns the returned status into a shell exit code, so
    # * `make` and any CI runner can tell success from failure.
    sys.exit(main(sys.argv[1:]))
