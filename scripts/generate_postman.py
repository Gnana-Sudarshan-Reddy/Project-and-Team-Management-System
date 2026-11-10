"""Generate docs/openapi.json and docs/postman_collection.json from the live FastAPI app.
Run:  python -m scripts.generate_postman
"""
import json
import os

os.environ.setdefault("LOG_FILE", "")
from app.main import app  # noqa: E402

SAMPLES = {
    "RegisterRequest": {"email": "user@example.com", "full_name": "Jane Doe", "password": "Secret123"},
    "UserCreate": {"email": "pm@example.com", "full_name": "Priya Manager", "password": "Secret123", "role_id": 2},
    "ProjectCreate": {"name": "Website Revamp", "description": "Redesign company site", "status": "active",
                      "start_date": "2026-11-01", "end_date": "2027-03-31", "member_ids": []},
    "ProjectUpdate": {"status": "on_hold"},
    "MemberAdd": {"user_id": 3},
    "TaskCreate": {"title": "Design homepage", "description": "Hero + CTA", "project_id": 1, "priority": "high",
                   "due_date": "2027-01-15", "assignee_id": 3},
    "TaskUpdate": {"status": "in_progress"},
    "CommentCreate": {"content": "Started working on this."},
    "UserProfileUpdate": {"full_name": "New Name"},
    "UserAdminUpdate": {"full_name": "New Name", "is_active": True},
    "UserStatusUpdate": {"is_active": False},
    "UserRoleUpdate": {"role_id": 2},
    "PasswordChange": {"current_password": "Secret123", "new_password": "NewSecret123"},
    "RolePermissionsUpdate": {"permissions": ["tasks:update_status", "comments:create"]},
}

LOGIN_TEST = ("const j = pm.response.json();\nif (j.access_token) { pm.collectionVariables.set('token', j.access_token); }")


def main() -> None:
    """Write the current OpenAPI document and a matching Postman collection."""
    spec = app.openapi()
    os.makedirs("docs", exist_ok=True)
    with open("docs/openapi.json", "w", encoding="utf-8") as openapi_file:
        json.dump(spec, openapi_file, indent=2)

    folders: dict[str, list] = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            tag = (op.get("tags") or ["Other"])[0]
            url_path = path.replace("{", ":").replace("}", "")
            parts = [p for p in url_path.split("/") if p]
            query = [{"key": p["name"], "value": "", "disabled": True}
                     for p in op.get("parameters", []) if p["in"] == "query"]
            req = {"method": method.upper(), "header": [], "url": {
                "raw": "{{base_url}}" + url_path, "host": ["{{base_url}}"], "path": parts, "query": query}}
            if "/auth/login" in path:
                req["body"] = {"mode": "urlencoded", "urlencoded": [
                    {"key": "username", "value": "admin@example.com"}, {"key": "password", "value": "Admin@12345"}]}
            elif "requestBody" in op:
                schema = op["requestBody"]["content"].get("application/json", {}).get("schema", {})
                name = schema.get("$ref", "").split("/")[-1]
                req["header"].append({"key": "Content-Type", "value": "application/json"})
                req["body"] = {"mode": "raw", "raw": json.dumps(SAMPLES.get(name, {}), indent=2),
                               "options": {"raw": {"language": "json"}}}
            item = {"name": f"{method.upper()} {path} — {op.get('summary', '')}", "request": req}
            if "/auth/login" in path:
                item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": LOGIN_TEST.split("\n")}}]
            folders.setdefault(tag, []).append(item)

    collection = {
        "info": {"name": "Project & Team Management API",
                 "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                 "description": "Run 'POST /auth/login' first; the token is saved automatically."},
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]},
        "variable": [{"key": "base_url", "value": "http://localhost:8000/api/v1"}, {"key": "token", "value": ""}],
        "item": [{"name": t, "item": items} for t, items in folders.items()],
    }
    # Authentication endpoints are usable before a token has been obtained.
    for f in collection["item"]:
        for it in f["item"]:
            if "/auth/" in it["name"]:
                it["request"]["auth"] = {"type": "noauth"}
    with open("docs/postman_collection.json", "w", encoding="utf-8") as collection_file:
        json.dump(collection, collection_file, indent=2)
    print("wrote docs/openapi.json and docs/postman_collection.json")


if __name__ == "__main__":
    main()
