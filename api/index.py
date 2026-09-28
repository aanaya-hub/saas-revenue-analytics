"""
api/index.py — the entry point Vercel serves.

WHY THIS FILE EXISTS
Vercel runs serverless functions, not long-lived Python processes. It cannot run
`dashboard.py` directly, because that file ends with `app.run(...)` — a
development server that blocks forever on a port. Vercel needs something it can
import, hand one HTTP request to, and get a response from.

This file provides exactly that: it imports the Dash app and exposes the Flask
instance underneath it, which is a standard WSGI application. Vercel's Python
runtime knows what to do with a WSGI object.

THE ONE CONVENTION THAT MATTERS
The variable MUST be called `app`. Vercel's Python builder looks for a module
level name `app`, finds ours, and treats it as the request handler. Naming it
`server` or `handler` produces a build that succeeds and a deployment that
returns 500 for every request, with nothing obvious in the logs. That is why the
name carries a comment rather than being left to look like a style choice.

WHY sys.path IS EDITED
This file lives in `api/`, but `dashboard.py` — the application it imports —
lives in the repository root, one level up. When Vercel imports this module, the
root is not necessarily on Python's search path. Inserting it explicitly means
the import works whether the code is run from the repository root, from `api/`,
or from Vercel's build directory.
"""

import os
import sys

# * __file__ is .../api/index.py. One dirname gives .../api, a second gives the
# * repository root. insert(0, ...) puts it at the FRONT of the search path so
# * `dashboard` is found there rather than being shadowed by any other module of
# * the same name.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# * Importing dashboard runs its module-level code, which reads
# * reports/results.json. That file must therefore be bundled with this
# * function — Vercel includes only what it is told to, which is configured in
# * vercel.json under "includeFiles". If the deployment returns a message about
# * a missing results file, that setting is where to look.
from dashboard import app as dash_app

# ! The name must be `app`. See the docstring above — this is a convention, not
# ! a preference, and getting it wrong fails silently at runtime.
app = dash_app.server
