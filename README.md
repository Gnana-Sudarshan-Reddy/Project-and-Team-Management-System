# Project & Team Management API

A modular **FastAPI + SQLAlchemy 2.0 + Alembic** backend for managing projects, tasks and teams, with JWT authentication and role-based access control (Admin, Project Manager, Team Member).

## Features
- **Auth**: register, login (OAuth2 password flow), bcrypt password hashing, JWT access tokens
- **RBAC**: three roles with editable permission lists; project-level access (owner / member)
- **Users**: admin CRUD, profile update, change password, activate/deactivate, assign role
- **Projects**: CRUD, members, progress and task statistics
- **Tasks**: CRUD, assign, status/priority, filters + search + sort + pagination, deadline validation, "my tasks"
- **Comments & activity logs**: comments per task, full audit trail (who created/updated what, with old → new values)
- Validation + uniform JSON errors, request logging (rotating file), optional Sentry, Swagger/OpenAPI, Docker, 15 tests

## Project structure
```
app/
├── main.py              # app factory, middleware, startup seeding
├── core/                # config (env vars), security (JWT/bcrypt), permissions, exceptions, logging
├── db/                  # Base, engine/session, seed data (roles + first admin)
├── models/              # SQLAlchemy models (one file per entity)
├── schemas/             # Pydantic request/response models
├── services/            # business rules: access control, activity logging, helpers
└── api/
    ├── deps.py          # get_current_user, require_permission(...)
    ├── router.py
    └── routes/          # auth, users(+roles), projects, tasks, activity
alembic/                 # migrations      tests/   # pytest suite
docs/                    # ER diagram, openapi.json, Postman collection
```

## Quick start (SQLite, no database setup)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                    # edit SECRET_KEY!
alembic upgrade head                                    # create tables
uvicorn app.main:app --reload
```
- Swagger UI: http://localhost:8000/docs  ·  ReDoc: http://localhost:8000/redoc
- A first admin is seeded on startup from `.env` (default `admin@example.com` / `Admin@12345`).

## PostgreSQL
```bash
createdb pm_db       # then in .env:
DATABASE_URL=postgresql+psycopg2://pm_user:pm_pass@localhost:5432/pm_db
alembic upgrade head
```
Or just run everything with Docker: `docker compose up --build` (API on :8000, Postgres included).

## Environment variables
| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy URL (SQLite or PostgreSQL) | `sqlite:///./app.db` |
| `SECRET_KEY` | JWT signing key — **change in production** | `change-this-in-production` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime | `60` |
| `FIRST_ADMIN_EMAIL/PASSWORD/NAME` | Seeded admin account | see `.env.example` |
| `LOG_LEVEL`, `LOG_FILE` | Logging (empty `LOG_FILE` = console only) | `INFO`, `logs/app.log` |
| `SENTRY_DSN` | Optional error monitoring | unset |
| `AUTO_CREATE_TABLES` | Dev shortcut instead of Alembic | `false` |

## Roles & permissions
| Capability | Admin | Project Manager | Team Member |
|---|:-:|:-:|:-:|
| Manage users / roles / permissions | ✅ | – | – |
| List users | ✅ | ✅ | – |
| Create projects | ✅ | ✅ | – |
| Update / delete project, manage members | ✅ any | ✅ own | – |
| Create / update / delete / assign tasks | ✅ | ✅ (projects they belong to) | – |
| Change **status** of tasks assigned to them | ✅ | ✅ | ✅ |
| Comment on tasks, view project data | ✅ | ✅ (own/member) | ✅ (member) |
| Global activity log | ✅ | – | – |

Admin can adjust these via `PUT /api/v1/roles/{id}/permissions`.

## Main endpoints (prefix `/api/v1`)
| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login` |
| Users | `GET/PATCH /users/me`, `POST /users/me/change-password`, `POST/GET /users`, `GET/PATCH /users/{id}`, `PATCH /users/{id}/status`, `PATCH /users/{id}/role` |
| Roles | `GET /roles`, `PUT /roles/{id}/permissions` |
| Projects | `POST/GET /projects`, `GET/PATCH/DELETE /projects/{id}`, `GET/POST /projects/{id}/members`, `DELETE /projects/{id}/members/{user_id}`, `GET /projects/{id}/stats`, `GET /projects/{id}/activity` |
| Tasks | `POST/GET /tasks`, `GET /tasks/me`, `GET/PATCH/DELETE /tasks/{id}`, `POST/GET /tasks/{id}/comments`, `GET /tasks/{id}/activity` |
| Activity | `GET /activity` (admin) |

Task list filters: `project_id, status, priority, assignee_id, created_by_id, q, due_before, due_after, overdue, sort_by, order, page, size`.

Error format: `{"error": {"code": "validation_error", "message": "...", "details": [...]}}`

## Testing
```bash
pytest -q
```
Uses an in-memory SQLite database; covers auth, RBAC, users, projects, members, tasks, filters, pagination, comments, activity and stats.

## API documentation
- Live Swagger at `/docs`; static spec in `docs/openapi.json`
- Postman: import `docs/postman_collection.json` (run **POST /auth/login** first — token is saved automatically)
- Regenerate both: `python -m scripts.generate_postman`
- ER diagram: `docs/ER_DIAGRAM.md`

## Design decisions
- **Permissions in the DB, rules in services**: routes stay thin; `services/access.py` holds "who can see/touch what".
- **Activity logs are written in the same transaction** as the change they describe, so history never drifts.
- **Deactivation is enforced on every request** (not only at login), so existing tokens stop working immediately.
- Possible next steps: refresh tokens, WebSocket notifications, email on assignment, file attachments.
