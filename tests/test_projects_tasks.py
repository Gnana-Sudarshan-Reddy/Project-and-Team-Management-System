"""Integration tests for project, task, comment, and activity workflows."""

from datetime import date, timedelta

from tests.conftest import P

# These dates keep deadline tests relative to the day they are run.
TOMORROW = str(date.today() + timedelta(days=1))
YESTERDAY = str(date.today() - timedelta(days=1))


def new_project(client, h, member_ids=(), **extra):
    """Create a project for a test and return its response data."""
    r = client.post(f"{P}/projects", headers=h, json={"name": "Website Revamp", "member_ids": list(member_ids), **extra})
    assert r.status_code == 201, r.text
    return r.json()


def new_task(client, h, project_id, **extra):
    """Submit a task-creation request with convenient test defaults."""
    return client.post(f"{P}/tasks", headers=h, json={"title": "Design homepage", "project_id": project_id, **extra})


def test_project_crud_and_visibility(client, pm, member, admin):
    """Check project permissions, visibility, filtering, updates, and deletion."""
    assert client.post(f"{P}/projects", headers=member["h"], json={"name": "Nope nope"}).status_code == 403
    proj = new_project(client, pm["h"], [member["user"]["id"]])
    assert {m["id"] for m in proj["members"]} == {pm["user"]["id"], member["user"]["id"]}
    assert client.get(f"{P}/projects/{proj['id']}", headers=member["h"]).status_code == 200
    assert client.get(f"{P}/projects", headers=member["h"]).json()["total"] == 1
    # A registered user who is not a project member should not see the project.
    client.post(f"{P}/auth/register", json={"email": "out@test.com", "full_name": "Outsider", "password": "Secret123"})
    from tests.conftest import login
    out = login(client, "out@test.com", "Secret123")
    assert client.get(f"{P}/projects/{proj['id']}", headers=out).status_code == 403
    assert client.get(f"{P}/projects", headers=out).json()["total"] == 0
    # Verify owner-only updates, admin filtering, and deletion behavior.
    assert client.patch(f"{P}/projects/{proj['id']}", headers=pm["h"], json={"status": "active"}).json()["status"] == "active"
    assert client.patch(f"{P}/projects/{proj['id']}", headers=member["h"], json={"status": "on_hold"}).status_code == 403
    assert client.get(f"{P}/projects?status=active", headers=admin).json()["total"] == 1
    assert client.delete(f"{P}/projects/{proj['id']}", headers=pm["h"]).status_code == 204
    assert client.get(f"{P}/projects/{proj['id']}", headers=admin).status_code == 404


def test_project_date_validation(client, pm):
    """Reject projects whose end date is earlier than their start date."""
    r = client.post(f"{P}/projects", headers=pm["h"], json={"name": "Bad dates", "start_date": "2026-05-01", "end_date": "2026-04-01"})
    assert r.status_code == 422


def test_membership_management(client, pm, member):
    """Add and remove members while keeping task assignments consistent."""
    proj = new_project(client, pm["h"])
    pid, uid = proj["id"], member["user"]["id"]
    assert client.post(f"{P}/projects/{pid}/members", headers=pm["h"], json={"user_id": uid}).status_code == 201
    assert client.post(f"{P}/projects/{pid}/members", headers=pm["h"], json={"user_id": uid}).status_code == 409
    t = new_task(client, pm["h"], pid, assignee_id=uid).json()
    r = client.delete(f"{P}/projects/{pid}/members/{uid}", headers=pm["h"])
    assert r.status_code == 200
    assert client.get(f"{P}/tasks/{t['id']}", headers=pm["h"]).json()["assignee"] is None  # unassigned
    assert client.delete(f"{P}/projects/{pid}/members/{pm['user']['id']}", headers=pm["h"]).status_code == 400


def test_task_lifecycle_and_deadline_validation(client, pm, member):
    """Check task creation, valid deadlines, assignment, updates, and deletion."""
    pid = new_project(client, pm["h"], [member["user"]["id"]], end_date=str(date.today() + timedelta(days=10)))["id"]
    assert new_task(client, pm["h"], pid, due_date=YESTERDAY).status_code == 422
    assert new_task(client, pm["h"], pid, due_date=str(date.today() + timedelta(days=30))).status_code == 422  # after project end
    assert new_task(client, member["h"], pid).status_code == 403
    r = new_task(client, pm["h"], pid, due_date=TOMORROW, assignee_id=member["user"]["id"], priority="high")
    assert r.status_code == 201
    t = r.json()
    assert t["created_by"]["id"] == pm["user"]["id"] and t["is_overdue"] is False
    # Users outside the project cannot be assigned its tasks.
    assert client.patch(f"{P}/tasks/{t['id']}", headers=pm["h"], json={"assignee_id": 99999}).status_code == 404
    # Project managers with update permission may edit any task field.
    up = client.patch(f"{P}/tasks/{t['id']}", headers=pm["h"], json={"priority": "critical", "title": "Design homepage v2"})
    assert up.json()["priority"] == "critical" and up.json()["updated_by"]["id"] == pm["user"]["id"]
    assert client.delete(f"{P}/tasks/{t['id']}", headers=member["h"]).status_code == 403
    assert client.delete(f"{P}/tasks/{t['id']}", headers=pm["h"]).status_code == 204


def test_assignee_can_only_change_status(client, pm, member):
    """Let assignees change status but not edit other fields or others' tasks."""
    pid = new_project(client, pm["h"], [member["user"]["id"]])["id"]
    tid = new_task(client, pm["h"], pid, assignee_id=member["user"]["id"]).json()["id"]
    other = new_task(client, pm["h"], pid).json()["id"]  # unassigned
    assert client.patch(f"{P}/tasks/{tid}", headers=member["h"], json={"priority": "low"}).status_code == 403
    done = client.patch(f"{P}/tasks/{tid}", headers=member["h"], json={"status": "done"})
    assert done.status_code == 200 and done.json()["completed_at"] is not None
    assert client.patch(f"{P}/tasks/{other}", headers=member["h"], json={"status": "done"}).status_code == 403
    reopened = client.patch(f"{P}/tasks/{tid}", headers=member["h"], json={"status": "in_progress"}).json()
    assert reopened["completed_at"] is None


def test_filter_search_pagination_and_my_tasks(client, pm, member):
    """Verify task filters, sorting defaults, pagination, and personal task lists."""
    pid = new_project(client, pm["h"], [member["user"]["id"]])["id"]
    uid = member["user"]["id"]
    for i in range(5):
        new_task(client, pm["h"], pid, title=f"Backend task {i}", priority="high" if i < 2 else "low", assignee_id=uid if i % 2 == 0 else None)
    new_task(client, pm["h"], pid, title="Write docs", description="README and swagger")
    r = client.get(f"{P}/tasks?page=1&size=4", headers=pm["h"]).json()
    assert r["total"] == 6 and len(r["items"]) == 4 and r["pages"] == 2
    assert client.get(f"{P}/tasks?priority=high", headers=pm["h"]).json()["total"] == 2
    assert client.get(f"{P}/tasks?q=swagger", headers=pm["h"]).json()["total"] == 1
    assert client.get(f"{P}/tasks?assignee_id={uid}", headers=pm["h"]).json()["total"] == 3
    assert client.get(f"{P}/tasks?overdue=false", headers=pm["h"]).json()["total"] == 6
    assert client.get(f"{P}/tasks?project_id=0", headers=pm["h"]).json()["total"] == 0
    mine = client.get(f"{P}/tasks/me", headers=member["h"]).json()
    assert mine["total"] == 3 and all(t["assignee"]["id"] == uid for t in mine["items"])
    assert client.get(f"{P}/tasks?size=1000", headers=pm["h"]).status_code == 422
    assert client.get(f"{P}/tasks?status=bogus", headers=pm["h"]).status_code == 422


def test_stats_comments_and_activity(client, pm, member, admin):
    """Verify project statistics, task comments, audit history, and retention."""
    pid = new_project(client, pm["h"], [member["user"]["id"]])["id"]
    uid = member["user"]["id"]
    t1 = new_task(client, pm["h"], pid, assignee_id=uid).json()["id"]
    new_task(client, pm["h"], pid, title="Second task")
    client.patch(f"{P}/tasks/{t1}", headers=member["h"], json={"status": "done"})

    s = client.get(f"{P}/projects/{pid}/stats", headers=pm["h"]).json()
    assert s["total_tasks"] == 2 and s["completed_tasks"] == 1 and s["progress_percent"] == 50.0
    assert s["by_status"]["done"] == 1 and s["by_status"]["todo"] == 1

    c = client.post(f"{P}/tasks/{t1}/comments", headers=member["h"], json={"content": "Finished!"})
    assert c.status_code == 201 and c.json()["user"]["id"] == uid
    assert client.post(f"{P}/tasks/{t1}/comments", headers=member["h"], json={"content": ""}).status_code == 422
    assert client.get(f"{P}/tasks/{t1}/comments", headers=pm["h"]).json()["total"] == 1

    actions = [a["action"] for a in client.get(f"{P}/tasks/{t1}/activity", headers=pm["h"]).json()["items"]]
    assert {"task.created", "task.status_changed", "task.commented"} <= set(actions)
    assert client.get(f"{P}/projects/{pid}/activity", headers=pm["h"]).json()["total"] >= 4

    # The audit event remains available after its project has been deleted.
    client.delete(f"{P}/projects/{pid}", headers=pm["h"])
    assert client.get(f"{P}/activity?action=project.deleted", headers=admin).json()["total"] == 1
