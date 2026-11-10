"""Integration tests for registration, authentication, user management, and roles."""

from tests.conftest import P, login


def test_register_login_and_me(client):
    """Registration should create a member account that can sign in."""
    r = client.post(f"{P}/auth/register", json={"email": "New@Test.com", "full_name": "New User", "password": "Secret123"})
    assert r.status_code == 201
    assert r.json()["role"]["name"] == "Team Member"
    assert "hashed_password" not in r.json()
    h = login(client, "new@test.com", "Secret123")
    assert client.get(f"{P}/users/me", headers=h).json()["email"] == "new@test.com"


def test_duplicate_email_and_weak_password(client):
    """Reject duplicate email addresses and passwords that fail validation."""
    body = {"email": "a@test.com", "full_name": "Aaa", "password": "Secret123"}
    assert client.post(f"{P}/auth/register", json=body).status_code == 201
    assert client.post(f"{P}/auth/register", json=body).status_code == 409
    weak = client.post(f"{P}/auth/register", json={**body, "email": "b@test.com", "password": "onlyletters"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "validation_error"


def test_bad_login_and_missing_token(client):
    """Require valid credentials and a bearer token for protected endpoints."""
    assert client.post(f"{P}/auth/login", data={"username": "x@y.com", "password": "nope12345"}).status_code == 401
    assert client.get(f"{P}/users/me").status_code == 401
    assert client.get(f"{P}/users/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_rbac_on_user_management(client, admin, pm, member):
    """Enforce user and activity permissions according to each role."""
    assert client.get(f"{P}/users", headers=member["h"]).status_code == 403  # no users:read
    assert client.get(f"{P}/users", headers=pm["h"]).status_code == 200
    assert client.post(f"{P}/users", headers=pm["h"], json={}).status_code == 403
    assert client.get(f"{P}/activity", headers=pm["h"]).status_code == 403
    assert client.get(f"{P}/activity", headers=admin).status_code == 200


def test_deactivate_user_blocks_login_and_token(client, admin, member):
    """Block both new and existing authentication for a deactivated user."""
    uid = member["user"]["id"]
    assert client.patch(f"{P}/users/{uid}/status", headers=admin, json={"is_active": False}).status_code == 200
    assert client.get(f"{P}/users/me", headers=member["h"]).status_code == 403
    r = client.post(f"{P}/auth/login", data={"username": "dev@test.com", "password": "Passw0rd123"})
    assert r.status_code == 403
    client.patch(f"{P}/users/{uid}/status", headers=admin, json={"is_active": True})
    assert client.get(f"{P}/users/me", headers=member["h"]).status_code == 200


def test_assign_role_and_self_protection(client, admin, member):
    """Allow role assignment but prevent an administrator from self-demotion."""
    roles = {r["name"]: r["id"] for r in client.get(f"{P}/roles", headers=admin).json()}
    r = client.patch(f"{P}/users/{member['user']['id']}/role", headers=admin, json={"role_id": roles["Project Manager"]})
    assert r.json()["role"]["name"] == "Project Manager"
    me = client.get(f"{P}/users/me", headers=admin).json()
    assert client.patch(f"{P}/users/{me['id']}/status", headers=admin, json={"is_active": False}).status_code == 400


def test_profile_update_and_change_password(client, member):
    """Allow profile edits and require the current password for password changes."""
    h = member["h"]
    assert client.patch(f"{P}/users/me", headers=h, json={"full_name": "Dev Renamed"}).json()["full_name"] == "Dev Renamed"
    bad = client.post(f"{P}/users/me/change-password", headers=h, json={"current_password": "wrong", "new_password": "Newpass123"})
    assert bad.status_code == 400
    ok = client.post(f"{P}/users/me/change-password", headers=h, json={"current_password": "Passw0rd123", "new_password": "Newpass123"})
    assert ok.status_code == 200
    login(client, "dev@test.com", "Newpass123")


def test_edit_role_permissions(client, admin, member):
    """Apply valid role permissions and reject unknown permission names."""
    roles = {r["name"]: r for r in client.get(f"{P}/roles", headers=admin).json()}
    tm = roles["Team Member"]
    r = client.put(f"{P}/roles/{tm['id']}/permissions", headers=admin, json={"permissions": ["users:read", "comments:create"]})
    assert r.status_code == 200
    assert client.get(f"{P}/users", headers=member["h"]).status_code == 200  # now allowed
    bad = client.put(f"{P}/roles/{tm['id']}/permissions", headers=admin, json={"permissions": ["fly:moon"]})
    assert bad.status_code == 422
