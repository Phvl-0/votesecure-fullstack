# VoteSecure API

The backend of the VoteSecure lab: a FastAPI app (async SQLAlchemy, PostgreSQL) for accounts, elections, candidates and secret-ballot voting. It runs as the `api` service of the Docker Compose stack at the repo root (see the root README). This file is the API reference.

## How it is reached

In the lab stack the API is not published to your machine. nginx serves the web app on `http://127.0.0.1:8089` and forwards `/api/` to the API, removing the prefix: `POST /login` is reached as `/api/login`. nginx answers 404 for `/api/docs`, `/api/redoc` and `/api/openapi.json`, so the interactive docs are not public.

## Configuration

Two environment variables, both required. The app refuses to start without them.

- `DATABASE_URL`: the PostgreSQL connection string (async driver).
- `SECRET_KEY`: the key that signs the JWT tokens.

In the lab stack they come from the `.env` file at the repo root.

## Data model

Six tables, created at startup by `Base.metadata.create_all`. That call never alters an existing table, and there are no migrations: a schema change on an existing database needs manual SQL (or dropping the old table, as was done for the former `votes` table).

| Table | Holds |
|---|---|
| `users` | id (uuid string), unique email, hashed password, role (`voter` or `admin`), active flag, created_at |
| `elections` | id, title, description, start and end date, created_at. No stored status and no stored vote counter |
| `candidates` | id, election, name, party, bio, image, created_at. Deleted with their election |
| `vote_receipts` | who voted in which election. Unique on (election, user) |
| `ballots` | what was chosen: election and candidate only. No user and no timestamp |
| `audit_logs` | admin actions: user id, action, details (JSON text), created_at |

## Endpoints

Paths are shown as the API sees them. Through nginx they carry the `/api` prefix.

| Method and path | Who | What it does |
|---|---|---|
| `POST /register` | anyone | Creates a voter. Any `id` or `role` sent by the caller is ignored |
| `POST /login` | anyone | Returns a 30-minute JWT |
| `GET /me` | logged in | Echoes the token's claims. No database call |
| `GET /admin/users` | admin | Lists users (never the password hash) |
| `GET /elections` | logged in | Elections with their candidates. Status (`upcoming`, `active`, `ended`) is computed from the server clock |
| `POST /elections` | admin | Creates an election. Title required, dates must carry a timezone, end after start (else 422) |
| `DELETE /elections/{id}` | admin | Deletes an election with its candidates and ballots |
| `POST /elections/{id}/candidates` | admin | Adds a candidate, only while the election is upcoming (else 409) |
| `DELETE /candidates/{id}` | admin | Removes a candidate, only while the election is upcoming (else 409) |
| `POST /elections/{id}/votes` | logged in | Casts a vote. The voter is the token's user, never the request body. 404 unknown election, 409 not active, 422 candidate not in this election, 401 unknown user, 409 already voted |
| `GET /elections/{id}/my-vote` | logged in | Returns only `{"has_voted": true or false}` |
| `GET /results` | logged in | Tallies for elections that have started, live ones first, counted from the ballots. No voter ids |
| `GET /me/votes` | logged in | The caller's own history: which elections, never which candidate |
| `GET /admin/audit-logs` | admin | Audit entries, newest first (`limit` up to 500) |

## Ballot secrecy

A vote writes two rows in one transaction: a receipt (who voted) and a ballot (what was chosen). Nothing links them: the ballot has no user and no timestamp. The one-vote rule is a database constraint on the receipts, so two simultaneous votes cannot both succeed; the loser gets 409 and its ballot is rolled back with it.

Limit: this is not a perfect cryptographic secret ballot. Someone with full access to the database and server logs could still try to match a receipt with a ballot by timing.

## Roles and admins

New users always get the role `voter`. An admin has to be promoted directly in the database (run from the repo root):

```bash
docker compose exec db psql -U appuser -d authdb -c "UPDATE users SET role='admin' WHERE email='you@example.com';"
```

The role is read from the token, so a change only takes effect at the user's next login.

## Audit log

The server records `create_election`, `delete_election`, `add_candidate` and `delete_candidate` in the same transaction as the action. A refused action leaves no entry.

## Tests

65 automated tests (pytest), by my count: 55 for the API, 7 for security and 3 at database level. They cover sign-up and login, forged tokens (wrong key, `alg: none`, expired, no subject), role enforcement, elections, candidates, voting (including two simultaneous votes), results, vote history and the audit log. They run on every push in GitHub Actions (`.github/workflows/tests.yml`) against a throwaway Postgres container.

To run them locally, use a separate database so development data stays untouched. From the `backend` folder:

```bash
printf 'POSTGRES_PASSWORD=%s\nSECRET_KEY=%s\n' "$(openssl rand -hex 16)" "$(openssl rand -hex 32)" > .env && chmod 600 .env
docker compose up -d db
docker compose exec db psql -U appuser -d authdb -c "CREATE DATABASE authdb_test;"
docker compose run --rm --no-deps -v "$PWD":/app api sh -c 'export DATABASE_URL="${DATABASE_URL%/authdb}/authdb_test" && pip install -q -r requirements-dev.txt && python -m pytest -q'
```

Create `.env` only once: the database saves its password the first time it starts. Wait a few seconds after `up` until the database accepts connections before creating `authdb_test`. Test tools live in `requirements-dev.txt`, so they are not part of the production image.

## Security notes

- Secrets come from the environment, not from the code. The app refuses to start without `SECRET_KEY` and `DATABASE_URL`.
- The server decides everything. The role comes from the signed token and is checked per route, and the voter is always the token's user.
- Sign-up ignores any `id` or `role` sent by the caller. This closes a privilege-escalation (mass-assignment) bug found during testing.
- Passwords are hashed with bcrypt. Tokens are HS256 JWTs (PyJWT) that last 30 minutes.
- In the lab stack the database and the API are not published to the host. Only the web container is, bound to `127.0.0.1:8089`.

## Limitations

- Roles are read from the token, so promoting or demoting a user takes effect at their next login.
- The lab stack serves plain HTTP and is for local use only. TLS is not done.
- Interim tallies are visible while an election is running.
- The timing limit on ballot secrecy described above.
- No migrations: `create_all` never alters an existing table.
- Passwords are cut at bcrypt's 72-byte limit.
- The JWT library was changed from `python-jose` (which had an open critical vulnerability and no fixed release) to `PyJWT`, and password hashing calls `bcrypt` directly instead of `passlib`, which relies on `crypt` (removed in Python 3.13). Hashes made by the old code still verify, and tests cover this.
- The images are scanned with Trivy on every push (`.github/workflows/trivy.yml` and `images.yml`). The jobs fail on HIGH or CRITICAL findings that have a fix available; unfixed findings are ignored. A clean scan means no known vulnerabilities in the database at scan time, not that the app is secure.
- The original version of this project used Supabase. This setup uses a local PostgreSQL container instead.
