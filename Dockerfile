# ============================================================================
# Dockerfile — runs the SaaS revenue analytics dashboard as a self-contained
# container. Any host that takes a Dockerfile can run it; it is written for
# Hugging Face Spaces, which is this project's deployment target.
#
# WHAT IS INSIDE, AND WHAT IS DELIBERATELY NOT
#   The image installs two libraries (dash, plotly) and copies three files.
#   It does NOT install pandas, scikit-learn, XGBoost or the rest of the
#   analysis stack, because the dashboard computes nothing. It draws charts
#   from reports/results.json, a file produced ahead of time by analysis.py.
#
#   That single decision is what keeps this image at roughly 300 MB instead of
#   the ~1 GB the full analysis stack would need — and it is the same decision
#   that makes the dashboard start in about two seconds.
#
#   To REGENERATE results.json you run `make all` on an ordinary machine. That
#   work does not belong in a web container and is not attempted here.
# ============================================================================

FROM python:3.13-slim

# Hugging Face Spaces runs the container as user ID 1000, not as root. So we
# create a user with exactly that ID. Without it the runtime user would have no
# home directory and no ownership of the files we copy in.
RUN useradd -m -u 1000 user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

# WORKDIR must come before any COPY, so the files land in a directory the
# runtime user can actually read and write.
WORKDIR $HOME/app

# Dependencies are installed BEFORE the application code. Docker caches each
# instruction, so editing dashboard.py later rebuilds in seconds instead of
# re-downloading dash and plotly every time.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt gunicorn

# The application itself, and the one data file it reads. dashboard.py opens
# reports/results.json at import time and nothing else.
COPY --chown=user dashboard.py .
COPY --chown=user reports/results.json reports/results.json

# Drop root for everything that runs after this line.
USER user

# 7860 is the port Hugging Face Spaces expects, and the value declared as
# app_port in the Space's README. EXPOSE is documentation; the real binding
# happens in the CMD below.
EXPOSE 7860
ENV PORT=7860

# Lets the host ask the image whether the app is genuinely answering, rather
# than only whether the process exists. It uses Python's own HTTP client
# because curl is not in the slim base image and installing it for one line
# would be waste.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/', timeout=4).status == 200 else 1)"

# gunicorn is a production WSGI server. Unlike the development server bundled
# with Dash it serves several requests at once and survives a failed one.
# `dashboard:server` means "the object named `server` inside dashboard.py" —
# that object is the Flask instance Dash wraps, exposed for exactly this.
#
# --no-control-socket is load-bearing, not decoration. gunicorn 26 opens a
# control socket at /run/user/1000/gunicorn.ctl by default, and a container has
# no systemd user session, so it aborts that step with
# "Control server error: [Errno 30] Read-only file system". The error is not
# fatal — the server still answers — but it prints a scary ERROR line into the
# Space log on every single start, and a read-only dashboard has no use for a
# control socket. Verified locally: the flag removes the error.
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "2", "--threads", "4", "--timeout", "120", "--no-control-socket", "dashboard:server"]
