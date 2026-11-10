# Database Schema (ER Diagram)

Rendered automatically on GitHub (Mermaid).

```mermaid
erDiagram
    ROLES ||--o{ USERS : "has"
    USERS ||--o{ PROJECTS : "owns"
    USERS ||--o{ PROJECT_MEMBERS : "joins"
    PROJECTS ||--o{ PROJECT_MEMBERS : "has"
    PROJECTS ||--o{ TASKS : "contains"
    USERS ||--o{ TASKS : "assigned to"
    USERS ||--o{ TASKS : "created / updated by"
    TASKS ||--o{ TASK_COMMENTS : "has"
    USERS ||--o{ TASK_COMMENTS : "writes"
    USERS ||--o{ ACTIVITY_LOGS : "performs"
    PROJECTS ||--o{ ACTIVITY_LOGS : "about"
    TASKS ||--o{ ACTIVITY_LOGS : "about"

    ROLES {
        int id PK
        string name UK
        string description
        json permissions
    }
    USERS {
        int id PK
        string email UK
        string full_name
        string hashed_password
        bool is_active
        int role_id FK
        datetime created_at
        datetime updated_at
    }
    PROJECTS {
        int id PK
        string name
        text description
        string status
        date start_date
        date end_date
        int owner_id FK
        datetime created_at
        datetime updated_at
    }
    PROJECT_MEMBERS {
        int id PK
        int project_id FK
        int user_id FK
    }
    TASKS {
        int id PK
        string title
        text description
        string status
        string priority
        date due_date
        datetime completed_at
        int project_id FK
        int assignee_id FK
        int created_by_id FK
        int updated_by_id FK
        datetime created_at
        datetime updated_at
    }
    TASK_COMMENTS {
        int id PK
        int task_id FK
        int user_id FK
        text content
        datetime created_at
    }
    ACTIVITY_LOGS {
        int id PK
        int user_id FK
        int project_id FK
        int task_id FK
        string action
        json details
        datetime created_at
    }
```

## Relationship notes
- **Users ↔ Roles**: many-to-one. A role carries a JSON list of permissions, so Admin can change what a role may do.
- **Projects ↔ Users**: many-to-many through `project_members` (unique on `project_id + user_id`), plus a separate `owner_id`.
- **Tasks** belong to one project (`ON DELETE CASCADE`); `assignee_id`, `created_by_id`, `updated_by_id` use `ON DELETE SET NULL`.
- **Task comments** cascade-delete with the task.
- **Activity logs** use `SET NULL` on project/task, so the audit trail survives deletions.
- Indexes: `users.email`, task `status/priority/due_date/project_id/assignee_id`, activity `action/created_at`.
