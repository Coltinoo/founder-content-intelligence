# Deployment

The app runs with **zero credentials** on SQLite. Everything below is about
running it somewhere persistent and scheduled.

---

## 1. Streamlit Community Cloud (simplest)

Free, and the fastest way to get a shareable URL.

1. Push this repository to GitHub.
2. [share.streamlit.io](https://share.streamlit.io) → **New app** → point at
   `streamlit_app.py`, Python 3.11.
3. **App settings → Secrets** — add the same names as `.env`:
   ```toml
   FCIE_DATABASE_URL = "postgresql+psycopg2://postgres.<ref>:<pw>@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
   OPENAI_API_KEY = "sk-..."
   TAVILY_API_KEY = "tvly-..."
   YOUTUBE_API_KEY = "..."
   ```
4. Deploy.

> **Set `FCIE_DATABASE_URL`.** The container filesystem is ephemeral, so a SQLite
> file is lost on every restart and redeploy. Without it the app still runs, but
> the library empties itself unpredictably.

**Ingestion:** don't run long crawls in the web dyno. Let the included GitHub
Action write to Supabase on a schedule; the app just reads the shared database.

---

## 2. Supabase (recommended database)

1. Create a project at [supabase.com](https://supabase.com).
2. **Project Settings → Database → Connection string → URI**, session pooler.
3. Convert the scheme for SQLAlchemy:
   ```
   postgresql+psycopg2://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
4. ```bash
   export FCIE_DATABASE_URL="postgresql+psycopg2://..."
   python scripts/init_db.py
   ```

No code changes. The models are dialect-neutral — JSON is stored as `TEXT` via
`JSONList`/`JSONDict`, so nothing is Postgres- or SQLite-specific.

Use the **session pooler** (port 5432), not the transaction pooler, since
SQLAlchemy holds connections across statements. `pool_pre_ping` is already on.

---

## 3. Render

**Web service**
```
Build:  pip install -r requirements.txt
Start:  streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0
```
Add the environment variables from `.env.example`. `FCIE_DATABASE_URL` is
required — Render's disk is ephemeral on the free tier too.

**Cron job** (separate service, same repo and env)
```
Command:  python scripts/run_discovery.py --max-sources 60
Schedule: 0 6 * * 1-5
```

## 4. Railway

Same shape. `railway.json`:
```json
{
  "build":  { "builder": "NIXPACKS" },
  "deploy": {
    "startCommand": "streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0",
    "restartPolicyType": "ON_FAILURE"
  }
}
```
Add a Railway cron service running `python scripts/run_discovery.py`.

## 5. Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
```
```bash
docker build -t fcie .
docker run -p 8501:8501 --env-file .env fcie
```

---

## Scheduling ingestion

All three entry points call the same `run_full_pipeline()`, so they cannot drift:

| Entry point | Use |
|---|---|
| Dashboard → **Run discovery** | demos, ad-hoc refresh |
| `python scripts/run_discovery.py` | cron, Task Scheduler, container jobs |
| `.github/workflows/discovery.yml` | hosted schedule, no infrastructure |

The GitHub Action runs weekdays 06:00 UTC, supports `workflow_dispatch` with
`max_sources` and `force_heuristic` inputs, uploads a JSON run summary as an
artifact, and **emits a warning when `FCIE_DATABASE_URL` is unset** rather than
silently discarding the run. Add repository secrets under
*Settings → Secrets and variables → Actions*.

```cron
0 6 * * 1-5  cd /opt/fcie && /opt/fcie/.venv/bin/python scripts/run_discovery.py >> /var/log/fcie.log 2>&1
```

---

## Pre-deployment checklist

- [ ] `.env` is git-ignored and no key is committed (`git log -S "sk-"` to be sure)
- [ ] `FCIE_DATABASE_URL` points at Supabase, not SQLite
- [ ] `python scripts/init_db.py` has run against the target database
- [ ] `python -m pytest tests` passes (205 tests)
- [ ] `python scripts/verify_feeds.py` — feeds still return entries
- [ ] `FCIE_RESPECT_ROBOTS` is **not** set to 0
- [ ] `FCIE_USER_AGENT` identifies you and is contactable
- [ ] `FCIE_CRAWL_DELAY_SECONDS` ≥ 2.0 on a shared/hosted runner
- [ ] The disclaimer is intact in `fcie/__init__.py` and on every page

## Operational notes

**Crawl politeness at scale.** Raise `FCIE_CRAWL_DELAY_SECONDS` to 2.5-3.0 on
hosted runners — many sites treat cloud IP ranges more strictly, and a shared
runner IP is not yours alone.

**Cost.** With `gpt-4o-mini`, one extraction is roughly 4-6k prompt tokens; a
60-source run is a few cents. Brief and draft generation add a handful of calls.
Set `ai.enable_llm: false` in `config/settings.yaml` to force the free
deterministic path.

**Scaling.** Streamlit is single-process with no auth — fine for a demo, not for
multi-tenant use. If it needs to serve a team: put auth in front, move ingestion
fully into the scheduled job, and add pgvector for semantic dedupe.

**Database growth.** `raw_text` is capped at 400k characters per source. At ~60
sources/day expect a few hundred MB per year — well inside Supabase's free tier,
but prune `raw_text` on old rows if it matters (`cleaned_text` is what the
pipeline actually reads).
