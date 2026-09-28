# ============================================================================
# Makefile — the project's task runner.
#
# Usage:  make <target>          e.g.  make generate
#         make help              lists every target and what it does
#
# HOW TO READ THIS FILE
# A Makefile is a list of named tasks. Each block is:
#
#     target_name:            <- the name you type after "make"
#         <TAB>command        <- the shell command that runs
#
# The indentation MUST be a real TAB character, not spaces. That is the single
# most common error in a Makefile, and the error message ("missing separator")
# does not explain it.
#
# `.PHONY` below tells make that these names are not files. Without it, make
# would look for a file called "test" and, finding none, still run the command —
# but if a file of that name ever appeared, the task would silently stop running.
# ============================================================================

.PHONY: help setup all generate analyse serve test clean

# --- help -------------------------------------------------------------------
# The default target runs first when you type just `make`. Listing the targets
# means nobody has to open this file to remember what is available.
help:
	@echo "setup     create the venv-saas environment and install requirements"
	@echo "all       run the whole pipeline in one command (main.py)"
	@echo "generate  build the synthetic star schema (CSV + SQLite + zip)"
	@echo "analyse   clean, model, and write figures + results.json"
	@echo "serve     start the Dash dashboard at http://127.0.0.1:8050"
	@echo "test      run the pytest suite"
	@echo "clean     remove generated data, figures and Python caches"

# --- setup ------------------------------------------------------------------
# Creates the virtual environment and installs the FULL analysis stack from
# requirements-analysis.txt, which includes requirements.txt. The deployment
# host installs only requirements.txt — see the note at the top of that file.
# The environment is named venv-saas so it is obvious which project it belongs
# to when several exist side by side.
#
# `&&` chains the commands so that each one only runs if the previous succeeded.
# Without it, a failed install would be followed by an attempt to use an
# environment that was never built, and the confusing error would appear far
# from the real cause.
setup:
	python3 -m venv venv-saas && ./venv-saas/bin/pip install --upgrade pip && ./venv-saas/bin/pip install -r requirements-analysis.txt

# --- all --------------------------------------------------------------------
# One command for everything. Delegates to main.py, which runs each step in its
# own process so a failure names the step that failed.
all:
	./venv-saas/bin/python main.py

# --- generate ---------------------------------------------------------------
# Builds the synthetic data. Deterministic: the same seed always produces the
# same rows, so re-running this is safe and the outputs are comparable.
generate:
	./venv-saas/bin/python data_gen.py

# --- analyse ----------------------------------------------------------------
# Cleans the data, runs EDA, fits the regression, churn and clustering models,
# and writes reports/results.json — the only thing the dashboard reads.
#
# This must run BEFORE `make serve`. The dashboard deliberately does not import
# scikit-learn or xgboost (they are too large to deploy), so it has nothing to
# show until this step has produced its JSON.
analyse:
	./venv-saas/bin/python analysis.py

# --- serve ------------------------------------------------------------------
# Starts the Dash development server. It listens on port 8050, so the dashboard
# is at http://127.0.0.1:8050 once it is running. Stop it with Ctrl+C.
serve:
	./venv-saas/bin/python dashboard.py

# --- test -------------------------------------------------------------------
# `-m pytest` runs pytest as a module — more reliable than calling the pytest
# binary directly, because it uses the interpreter you just invoked.
# `-q` is quiet mode: one dot per passing test instead of a wall of text.
test:
	./venv-saas/bin/python -m pytest -q

# --- clean ------------------------------------------------------------------
# Deletes everything the pipeline produces, keeping the source and the
# environment. Useful when a result looks wrong and the first question is
# "is the data stale?".
#
# The second line uses `find` to locate every __pycache__ folder and remove it.
# `-prune` stops find from descending into a folder it is about to delete.
clean:
	rm -f data/raw/*.csv data/raw/*.db data/raw/*.zip reports/figures/*.png reports/*.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
