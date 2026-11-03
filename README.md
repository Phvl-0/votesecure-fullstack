# VoteSecure Lab

A practice lab that mimics real DevSecOps work. A voting app's frontend (Vite, React, TypeScript) talks to my own FastAPI backend instead of Supabase, and everything runs in Docker Compose: nginx, FastAPI and PostgreSQL. Every change goes through a branch and a pull request, CI runs the tests and a Trivy scan, and the images are published to GitHub's registry (ghcr.io).

The live app is a separate repo ([Online-Election-System](https://github.com/Phvl-0/Online-Election-System), Lovable and Supabase) and is untouched by this lab. The API started as [FastAPI-Auth-Compose](https://github.com/Phvl-0/FastAPI-Auth-Compose).

## Architecture

```
browser --> nginx (web container) --> FastAPI (api) --> PostgreSQL (db, volume pgdata)
            serves the React app       14 routes         users, elections, candidates,
            proxies /api/ to the api                     vote_receipts, ballots, audit_logs
```

- **web**: nginx serves the built React app (with fallback to `index.html` for client-side routes) and forwards `/api/` to the API, removing the prefix. It blocks `/api/docs`, `/api/redoc` and `/api/openapi.json`, sends `nosniff` and `X-Frame-Options: DENY`, and hides its version.
- **api**: the FastAPI app. It waits for a healthy database and refuses to start without `SECRET_KEY` and `DATABASE_URL`. See [backend/README.md](backend/README.md) for the routes and the data model.
- **db**: PostgreSQL 16 with a named volume, so data survives restarts.
- Only `web` is published to the host, and only on `127.0.0.1:8089`. The API and the database are reachable only inside the Compose network.

## Run it

Requirements: Docker with Compose, and a Unix-style shell with `openssl` (Linux, macOS or WSL).

1. Clone the repo:

```bash
git clone https://github.com/Phvl-0/votesecure-fullstack.git
cd votesecure-fullstack
```

2. Create your own `.env` with random secrets (it is ignored by Git). `.env.example` shows the two variable names:

```bash
printf 'POSTGRES_PASSWORD=%s\nSECRET_KEY=%s\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" > .env
chmod 600 .env
```

Create `.env` only once. The database saves its password the first time it starts, so a different `.env` created later will not match it. To start over, run `docker compose down -v` first (this deletes the data).

3. Build and start everything:

```bash
docker compose up -d --build --wait
```

The first build downloads the frontend dependencies. On a slow connection `npm ci` can time out: run the command again.

4. Open http://localhost:8089.

Stop it with `docker compose down` (keeps the data) or `docker compose down -v` (also deletes the database volume). If port 8089 is taken, change the `ports` line of the `web` service in `docker-compose.yml`.

## Using the app

- **Voters** register, log in, vote in elections that are active, and see tallies on the Results page. My Profile lists the elections they voted in, but never who they voted for.
- **Admins** get an admin dashboard to create and delete elections and to add or remove candidates. Admins can only be made in the database. Register in the app, then promote the account:

```bash
docker compose exec db psql -U appuser -d authdb -c "UPDATE users SET role='admin' WHERE email='you@example.com';"
```

The role is read from the token, so log out and log in again.

- **Election rules:** status (`upcoming`, `active`, `ended`) comes from the server clock. Candidates can only be added or removed while an election is upcoming, so create it with a start a few minutes ahead, add the candidates, wait for the start, then vote.

## Security design

- **The server decides everything.** Roles are checked per route, the voter is always the token's user (never the request body), and registration ignores any `id` or `role` sent. The browser only decodes the token to decide what to display.
- **Secret ballots.** A vote writes two rows in one transaction: a receipt in `vote_receipts` (who voted) and a ballot in `ballots` (what was chosen, with no user and no timestamp). Results count ballots, and the history page shows elections only.
- **One vote per person per election is a database constraint**, not a check in the code, so two simultaneous votes cannot both succeed.
- **Audit log.** Creating or deleting an election and adding or removing a candidate are logged in the same transaction as the action. A refused action leaves no entry.
- **Tokens** are HS256 JWTs that last 30 minutes. Forged tokens (wrong key, `alg: none`, expired, no subject) are rejected, and tests cover each case. A damaged token in the browser leads to a "Session expired" screen.
- **Secrets** live in `.env`, which Git ignores. Passwords are hashed with bcrypt.

## CI and images

| Workflow | What it does |
|---|---|
| `tests.yml` | Runs the backend tests against a throwaway PostgreSQL |
| `trivy.yml` | Builds the backend image and scans it with Trivy |
| `frontend.yml` | `npm ci`, TypeScript type-check, production build |
| `images.yml` | Builds both images, scans both with Trivy, and pushes them to ghcr.io only from `main` |

- Trivy fails the run on HIGH or CRITICAL findings that have a fix. Unfixed findings are ignored. A clean scan means no known vulnerabilities at scan time, not that the app is secure.
- Images: `ghcr.io/phvl-0/votesecure-fullstack-api` and `ghcr.io/phvl-0/votesecure-fullstack-web`, tagged with the commit SHA and `latest`. The packages are private (the default).
- All GitHub Actions are pinned by full commit SHA. The only third-party actions are checkout and Trivy; Docker login, build and push are plain commands.
- Trade-off: the images job holds `packages: write` on every push. The push steps only run on `main`.

## Tests

65 backend tests (pytest). Several rules were also sabotage-checked: break the rule on purpose, watch its test go red, then restore it. To run them locally, follow the instructions in [backend/README.md](backend/README.md#tests). The frontend is type-checked and built in CI, and was checked by hand in a browser (register, promote to admin, create an election, vote, results, history, session expiry).

## Limitations

- Plain HTTP, local use only. TLS is not done.
- The login token is kept in `localStorage`, so a script injected into the page could read it. Tokens last 30 minutes.
- Interim tallies are visible while an election is running.
- The admin session ends when the 30-minute token does. Role changes take effect at the next login.
- Ballot secrecy is not cryptographic: someone with full access to the database and server logs could try to match a receipt and a ballot by timing.
- No migrations: tables are created at startup and never altered, so a schema change on an existing database needs manual SQL.
- No profile username or avatar, no election images, and no live push updates (pages refresh every 15 seconds). There is no single-election endpoint, so the page picks the election from the list.

## Repository layout

| Path | What it holds |
|---|---|
| `src/` | The React frontend. `src/lib/api.ts` is the API client |
| `backend/` | The FastAPI app, its tests and its README |
| `Dockerfile`, `nginx.conf` | The web image: Node build stage, then nginx |
| `docker-compose.yml` | The stack: `db`, `api`, `web` |
| `.github/workflows/` | CI workflows |
| `.env.example` | The two variables `.env` needs |
