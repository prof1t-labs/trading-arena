# Trading Arena SaaS — Vercel deployment

This package converts the browser-only prototype into a deployable FastAPI application with:

- account registration and login;
- bcrypt password hashing;
- revocable, HTTP-only cookie sessions;
- a PostgreSQL-backed workspace document for orders, positions, strategies, risk settings, integrations and audit data;
- a generic `dataset_records` table and API for future market, evaluation or webhook datasets;
- SQLite fallback for local development;
- a Vercel-compatible FastAPI entrypoint and static frontend.

## 1. Run locally

Use Python 3.12.

```bash
python -m venv .venv
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install and run:

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

Without `DATABASE_URL`, the app creates `trading_arena.db` locally. Set `COOKIE_SECURE=false` for plain HTTP local development.

## 2. Put the project on GitHub

```bash
git init
git add .
git commit -m "Deploy Trading Arena SaaS"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/trading-arena.git
git push -u origin main
```

## 3. Create the Vercel project

1. Sign in to Vercel.
2. Select **Add New → Project**.
3. Import the GitHub repository.
4. Keep the detected FastAPI settings.
5. Do not deploy production yet if `DATABASE_URL` is not configured.

You can also use the CLI:

```bash
npm install -g vercel
vercel
```

## 4. Add PostgreSQL through Neon

In the Vercel project:

1. Open **Storage** or **Marketplace**.
2. Install **Neon Postgres**.
3. Create a database in the region nearest your users.
4. Connect it to the Vercel project for Production, Preview and Development.
5. Confirm that Vercel injected `DATABASE_URL`.

The application automatically creates its initial tables on the first API cold start. For a larger production release, replace this with Alembic migrations.

## 5. Environment variables

Set these in **Project Settings → Environment Variables**:

```text
DATABASE_URL=<injected by Neon>
COOKIE_SECURE=true
SESSION_DAYS=14
```

Apply them to Production, Preview and Development as appropriate. Redeploy after changing environment variables.

## 6. Deploy

From Git, push to `main`, or use:

```bash
vercel --prod
```

After deployment, test:

```text
https://YOUR_PROJECT.vercel.app/api/health
```

Then open the root URL, create an account, sign out and sign back in. Place a paper order or create a strategy, refresh the page, and confirm that the workspace is restored.

## 7. Pull production variables for local testing

```bash
vercel link
vercel env pull .env
```

Then run:

```bash
uvicorn app:app --reload
```

Be careful: this can connect local development to the production database. A separate Neon development branch is safer.

## 8. API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Deployment health |
| `POST` | `/api/auth/register` | Create account |
| `POST` | `/api/auth/login` | Start session |
| `GET` | `/api/auth/me` | Current user |
| `POST` | `/api/auth/logout` | Revoke session |
| `GET` | `/api/workspace` | Load workspace |
| `PUT` | `/api/workspace` | Save workspace |
| `GET` | `/api/datasets` | List typed dataset records |
| `POST` | `/api/datasets` | Add a typed dataset record |

Interactive API documentation is available at `/docs`.

## 9. Important production boundary

Vercel is suitable for this authentication and CRUD API, but the full trading architecture should not run entirely inside request-response functions. Keep the frontend and ordinary API on Vercel, then use a long-running container service for:

- Alpaca streaming connections;
- durable WebSockets;
- order/event consumers;
- scheduled reconciliation workers;
- strategy execution and sandboxing;
- NautilusTrader replay jobs;
- compute-heavy analytics.

A practical next deployment split is:

```text
Vercel
  ├─ frontend
  ├─ authentication
  ├─ CRUD API
  └─ TradingView webhook ingestion

Neon
  └─ PostgreSQL

Railway / Fly.io / Render
  ├─ market-data stream worker
  ├─ broker execution worker
  ├─ WebSocket gateway
  └─ strategy/replay workers
```

## 10. Security work before public launch

This package is an MVP deployment baseline, not a finished financial production system. Before public use, add:

- email verification and password reset;
- rate limiting and bot protection;
- multi-factor authentication;
- CSRF tokens if cross-origin clients are introduced;
- database migrations and backups;
- structured logs and alerting;
- secret rotation;
- tenant/workspace roles;
- encrypted broker credentials;
- webhook signatures and replay prevention;
- legal and compliance review.

Do not connect live brokerage funds until the execution service, reconciliation, controls and compliance requirements have been independently reviewed.
