# Deploying the dashboard to Render

> Written 2026-09-28. **This deployment is live:**
> **<https://saas-revenue-analytics.onrender.com>**
>
> Verified from outside on 2026-09-28: `/`, `/_dash-layout` and `/_dash-dependencies` all return 200,
> the layout carries all five tab labels, and six callbacks are registered. Those payloads are
> byte-for-byte identical to the local run.

## Why Render

Four hosts were tried before this one worked. The short version, because the reasons are more useful
than the outcome:

| Host | Outcome |
| --- | --- |
| Vercel | Configuration written and viable (74 MB against a 500 MB limit); deployment blocked at **account verification**, not by a technical limit |
| Netlify | Impossible. Functions run JavaScript and TypeScript only — their Python support is for *build* steps, not for serving an app |
| Hugging Face Spaces | Was the chosen target until **the pricing changed**: Docker Spaces now need PRO ($9/month). Only Static Spaces are free, and Static cannot run Python |
| **Render** | **Free, no credit card, Docker detected automatically. Live.** |

What made Render work is that it builds from a Dockerfile — so the image already written and tested
deployed with **no change to the application code at all**. That is the payoff for keeping the container
definition separate from the app.

## The exact settings used

After connecting the repository, **New → Web Service**:

| Field | Value |
| --- | --- |
| Repository | `aanaya-hub/saas-revenue-analytics` |
| Name | `saas-revenue-analytics` |
| Region | Oregon |
| Branch | `main` |
| Root Directory | *(blank)* |
| Runtime | Docker — auto-detected from the `Dockerfile` |
| Instance Type | **Free** |
| Build Command | *(not shown for Docker)* |
| Start Command | *(not shown for Docker)* |
| Environment Variables | **none** — Render injects `PORT` itself |
| Health Check Path | *(blank)* |

There are no secrets in this deployment, so there is nothing to put in environment variables. The `PORT`
that Render injects is read by the Dockerfile's `CMD`; the README's deployment section explains why that
matters.

**If the name is taken**, the URL changes with it — update the `**Live demo:**` line in the project README
and the Project 2 entry in `resume-master.md` to match.

## Redeploying

Render redeploys automatically on every push to `main`. To ship a refreshed analysis:

```bash
cd ~/Documents/DeepSeek_Folders/agente_poner_a_hacer_billetes/career/02-portfolio/projects/saas-revenue-analytics
make all                        # regenerates reports/results.json
git add reports/results.json
git commit -m "Refresh analysis results"
git push origin main            # Render rebuilds on its own
```

The dashboard reads `reports/results.json` at import time, so a stale file means stale numbers on the
live site even when the code is current. Regenerating the data without committing it changes nothing.

## Free tier behaviour — the honest version

Straight from Render's own documentation, because two of these will bite if ignored:

- **Sleeps after 15 minutes idle**, and the next request takes roughly **a minute** to wake it. That is
  platform behaviour, not a fault in this app — which is why the live link on the README carries a note.
- **750 instance hours per workspace per calendar month.** A service kept awake around the clock would
  consume roughly 730. Exceeding the cap **suspends free web services until the next month**, which would
  take the demo link down entirely.
- **No credit card required.** The free Postgres 30-day expiry that catches people out on Render does not
  apply here, because this app stores nothing.

### Cold start — DECIDED 2026-09-28: keep-alive during business hours only

The link is kept warm by a free external pinger on a **bounded duty cycle**. That option was chosen over
the other two because it is the only one that cannot end in a suspended service.

| Option | Effect | Instance hours/month | Verdict |
| --- | --- | --- | --- |
| Leave it sleeping | First visitor waits ~1 min | ~0 | rejected — a recruiter may click away |
| Pinger 24/7 | Always instant | ~730 of 750 | rejected — 20 h of margin is not worth risking suspension |
| **Pinger, 12 h/day** | **Instant through the US business day** | **~365 of 750 (49%)** | **adopted** |

**The window is 12:00–23:59 UTC.** In local terms:

| Reader | Local hours the app is awake |
| --- | --- |
| Guadalajara (UTC-6) | 06:00 – 18:00 |
| US Eastern (UTC-4) | 08:00 – 20:00 |
| US Central (UTC-5) | 07:00 – 19:00 |
| US Pacific (UTC-7) | 05:00 – 17:00 |

That covers the US business day in every mainland timezone. **EU mornings are not covered** — if that ever
matters, starting at 07:00 UTC instead raises usage to about 517 h/month, still inside the cap.

**The tool is [cron-job.org](https://cron-job.org).** It is genuinely free with no paid tier, which is why
it was chosen over UptimeRobot: UptimeRobot's only way to restrict hours is its *"maintenance window"*
feature, and that is **paid-only**.

**Setup:** one HTTP job, method `GET`, URL `https://saas-revenue-analytics.onrender.com/`, executed
**every 5 minutes** inside the window. Five minutes is deliberate — three times more frequent than Render's
15-minute sleep threshold, so a delayed execution still cannot let the instance sleep. That is roughly
**4,400 requests and about 19 MB a month**.

### Expect exactly one failed execution per day

Worth stating up front so it is not misread as a problem:

**cron-job.org abandons a request after 30 seconds. Waking a sleeping Render instance takes about a
minute.** So the first ping after the overnight gap times out — and that timed-out request is precisely
what wakes the service. The next ping, five minutes later, succeeds.

The job is only auto-disabled after **25 consecutive** failures, so a single daily timeout never triggers
it. **Leave the failure-notification email switched off**, or it arrives every morning and trains you to
ignore the one that would actually matter. Check the execution history instead when reviewing the campaign
each week.

### Why the ceiling mattered more than the cold start

Render suspends free web services that exhaust the 750-hour monthly cap. A suspended service serves an
error page, and **a dead link on a resume is worse than a slow one** — a slow link still loads, and the
README warns the reader. That asymmetry is what ruled out the 24/7 pinger, not the cost of the pings.

## Verifying a deploy

Once the badge reads **Live**:

```bash
URL=https://saas-revenue-analytics.onrender.com
curl -s -o /dev/null -w "%{http_code}\n" $URL/
curl -s -o /dev/null -w "%{http_code}\n" $URL/_dash-layout
curl -s -o /dev/null -w "%{http_code}\n" $URL/_dash-dependencies
```

All three should print `200`. The last two matter most: an app that serves the page but not those renders
blank, which looks like a styling problem rather than a routing one. Use a generous `--max-time` on the
first call — after a sleep it takes about a minute.

The first request after long idle periods is the one to watch. If it ever returns a Render error page
rather than the dashboard, the instance may have been suspended for exhausting its monthly hours.

## Where the URL belongs

| Place | State |
| --- | --- |
| Project README, `**Live demo:**` line | **done** |
| `career/01-resume/resume-master.md`, Project 2 entry | **done** |
| `career/03-channels/github-main-readme.md` landing page | **done** |
| `career/03-channels/linkedin-profile.md`, Featured section | **approval-gated** — not applied |
| GitHub repository description | **user action** — text in `03-channels/github-settings.md` |

Nothing on a public profile is changed without the user's explicit approval. The landing page and resume
are his own repositories and files, so those were updated in the workspace for him to push.
