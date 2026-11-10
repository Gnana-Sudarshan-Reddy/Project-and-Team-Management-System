"""Shared pytest fixtures for isolated API tests."""

import os
from collections.abc import Iterator
from typing import Any

# Set these before importing app modules so cached settings use the test database.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["LOG_FILE"] = ""
os.environ["FIRST_ADMIN_EMAIL"] = "admin@test.com"
os.environ["FIRST_ADMIN_PASSWORD"] = "Admin12345"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.init_db import init_db
from app.db.session import get_db
from app.main import app
import app.models as _models  # noqa: F401  (register models with Base.metadata)

P = "/api/v1"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """Provide an isolated in-memory database and API client for one test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    previous_overrides = app.dependency_overrides.copy()

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        """Make SQLite enforce foreign keys in the isolated test database."""
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    try:
        Base.metadata.create_all(engine)
        testing_session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        with testing_session_factory() as db:
            init_db(db)

        def override_get_db() -> Iterator[Session]:
            """Use a fresh session per request against this test's database."""
            db = testing_session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    """Log in through the API and return the Authorization header."""
    r = client.post(f"{P}/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client: TestClient) -> dict[str, str]:
    """Provide an authenticated header for the seeded administrator."""
    return login(client, "admin@test.com", "Admin12345")


def make_user(
    client: TestClient,
    admin: dict[str, str],
    email: str,
    role_name: str,
) -> dict[str, Any]:
    """Create a user with the requested role through the administrator API."""
    roles = {role["name"]: role["id"] for role in client.get(f"{P}/roles", headers=admin).json()}
    response = client.post(
        f"{P}/users",
        headers=admin,
        json={
            "email": email,
            "full_name": email.split("@")[0].title(),
            "password": "Passw0rd123",
            "role_id": roles[role_name],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def pm(client: TestClient, admin: dict[str, str]) -> dict[str, Any]:
    """Provide a project-manager user and that user's auth header."""
    user = make_user(client, admin, "pm@test.com", "Project Manager")
    return {"user": user, "h": login(client, "pm@test.com", "Passw0rd123")}


@pytest.fixture()
def member(client: TestClient, admin: dict[str, str]) -> dict[str, Any]:
    """Provide a team-member user and that user's auth header."""
    user = make_user(client, admin, "dev@test.com", "Team Member")
    return {"user": user, "h": login(client, "dev@test.com", "Passw0rd123")}
