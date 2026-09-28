# Deploying the dashboard to Hugging Face Spaces

> **SUPERSEDED 2026-09-28 — DO NOT FOLLOW THIS FILE YET.**
>
> Hugging Face changed their pricing, and this runbook was written without knowing it: **Docker and
> Gradio Spaces now require a paid plan.** Only **Static** Spaces are free. From the official
> [Spaces Overview](https://huggingface.co/docs/hub/en/spaces-overview):
>
> *"Static Spaces are free for everyone. Gradio and Docker Spaces run on compute and require a paid
> plan to create: PRO for personal accounts, Team or Enterprise for organizations."*
>
> PRO is **$9/month**, and it is a recurring charge — if the subscription lapses the Space most likely
> stops, which would kill a demo link the campaign needs alive for months.
>
> **What is still valid here:** the `Dockerfile` itself. It is correct and was verified locally against
> Hugging Face's documented container requirements (user ID 1000, `WORKDIR` before `COPY`,
> `--chown=user`, `--no-control-socket`). It will work unchanged on any Docker host that is free.
>
> **What is wrong:** the assumption that Spaces is a free target, and therefore the whole "create the
> Space and push" flow. That step cannot be completed on a free personal account.
>
> The deployment target is being re-decided. This file gets rewritten once it is chosen.

> Written 2026-09-25. Hugging Face Spaces runs Docker containers as **user ID 1000**, which the
> `Dockerfile` handles. Verified against the official
> [Docker Spaces documentation](https://github.com/huggingface/hub-docs/blob/main/docs/hub/spaces-sdks-docker.md).

## Why this host

Vercel was the first choice. The serverless configuration was written and the bundle would have fit —
roughly **74 MB against Vercel's 500 MB Python limit** — but deployment was blocked at **account
verification**, which is an obstacle on Vercel's side rather than a technical one. The configuration is
still in the repository because that path is not closed.

Netlify was the second choice and cannot work at all: its Functions runtime supports JavaScript and
TypeScript only, and the Python support Netlify documents is for *build* steps, not for serving an
application.

Spaces was the third choice and the first one without a catch: it accepts an arbitrary Dockerfile, so
no bundle ceiling and no imposed runtime apply.

## What the Space needs — exactly five files

| File in the Space | Comes from |
| --- | --- |
| `README.md` | `deploy/huggingface/space-README.md` |
| `Dockerfile` | `Dockerfile` (project root) |
| `dashboard.py` | `dashboard.py` |
| `requirements.txt` | `requirements.txt` |
| `reports/results.json` | `reports/results.json` |

Nothing else. `analysis.py`, `data_gen.py`, `config.py`, `main.py`, `tests/`, `data/raw/` and
`reports/figures/` are **not** copied — the container does not read them.

The Space's `README.md` is deliberately *not* the project README. Hugging Face requires the YAML
block (`sdk: docker`, `app_port: 7860`) at the very top of the Space's own `README.md`, and that
block would render as a stray table at the top of the GitHub project page. So the Space gets its own
front page, which links back to GitHub.

---

## Path A — git push (recommended, reliable)

### 1. Create the Space

Go to <https://huggingface.co/new-space> and fill in:

- **Owner / Space name:** `saas-revenue-analytics` (or any name)
- **License:** `mit`
- **Select the Space SDK:** **Docker** → **Blank**
- **Space hardware:** `CPU basic · 2 vCPU · 16 GB` (free)
- **Visibility:** Public

Creating the Space takes about a minute.

### 2. Clone it

Substitute your Hugging Face username for `<hf-user>`:

```bash
cd ~/Documents
git clone https://huggingface.co/spaces/<hf-user>/saas-revenue-analytics hf-space
cd hf-space
```

### 3. Copy the five files in

Run this from `hf-space`, adjusting the first path to wherever this repository lives:

```bash
PROJECT=~/Documents/DeepSeek_Folders/agente_poner_a_hacer_billetes/career/02-portfolio/projects/saas-revenue-analytics

cp "$PROJECT/Dockerfile" .
cp "$PROJECT/dashboard.py" .
cp "$PROJECT/requirements.txt" .
cp "$PROJECT/deploy/huggingface/space-README.md" README.md
mkdir -p reports
cp "$PROJECT/reports/results.json" reports/
```

Confirm you have exactly the right set before committing:

```bash
find . -type f -not -path './.git/*' | sort
```

Expected output — five files:

```
./Dockerfile
./README.md
./dashboard.py
./reports/results.json
./requirements.txt
```

### 4. Push

Hugging Face authenticates with a **token**, not your account password. Create one at
<https://huggingface.co/settings/tokens> with **Write** access, then:

```bash
git add -A
git commit -m "Deploy SaaS revenue analytics dashboard"
git push
```

When git asks for a password, paste the token. (Username: your Hugging Face username.)

### 5. Watch it build

The Space page shows a **Building** badge, then **Running**. First build takes roughly 3–6 minutes
because it downloads the `python:3.13-slim` base image and installs dash and plotly. Later builds
are much faster — Docker caches the dependency layer, so editing `dashboard.py` alone rebuilds in
seconds.

If it fails, the **Logs** tab shows the build output and then the gunicorn output. Paste the error
back and it can be diagnosed.

---

## Path B — web upload (no git required)

Use this if you would rather not deal with tokens.

1. Create the Space as above (**SDK: Docker**, Blank).
2. Open the **Files** tab → **Add file** → **Upload files**.
3. Upload `Dockerfile`, `dashboard.py`, `requirements.txt`, and `space-README.md` (rename it to
   `README.md` on upload, or overwrite the existing `README.md` afterwards).
4. For the data file, drag the whole `reports` folder in — the browser preserves the folder
   structure. If drag-and-drop flattens it, use **Add file → Create a new file**, type
   `reports/results.json` as the filename (the slash creates the folder), and paste the contents of
   the file in.
5. Commit each upload from the web form.

The result must be the same five files at the same paths as Path A, or the build will fail with
`file not found`.

---

## How to verify the deployment worked

Once the badge says **Running**:

1. The dashboard loads and the header reads *"Northwind Analytics · 200 customers · 4 months · seed
   20260901"*.
2. All five tabs open: **Executive**, **Revenue**, **Churn risk**, **Segments**, **Data & models**.
3. On **Churn risk**, moving the threshold slider changes the dollar figures. This is the one
   interactive element worth testing, because it exercises the Dash callback — if the callback is
   broken the page still renders, but the slider does nothing.
4. The page loads in under five seconds on a warm Space.

## Free-tier behaviour worth knowing

- A free Space **sleeps after 48 hours of inactivity**. The first visit after that takes 30–60
  seconds to wake. That is normal, not a failure — but if you are sending the link to a recruiter,
  open it yourself first so it is warm.
- Anything written to disk is lost on restart. This dashboard is read-only, so it does not care.
- Public Spaces are visible to everyone with the link, including the Dockerfile and the JSON. There
  are no secrets in any of the five files — no API keys, no credentials, no personal data.

## Updating the Space later

If `reports/results.json` is regenerated (because `analysis.py` changed), the Space must be updated
too or it will keep showing stale numbers:

```bash
cd ~/Documents/hf-space
cp "$PROJECT/reports/results.json" reports/
git add -A && git commit -m "Refresh analysis results" && git push
```

## Where the link goes once it works

The Space URL (`https://huggingface.co/spaces/<hf-user>/saas-revenue-analytics`) is the **live demo**
link. It belongs in three places:

1. The project README on GitHub, on the `**Live demo:**` line at the top.
2. `career/01-resume/resume-master.md`, in the Project 2 entry.
3. `career/03-channels/linkedin-profile.md`, in the Featured section — **not** before you have
   approved the wording, and not before the Space is public.

All three of those are approval-gated. Nothing above changes a public profile on its own.
