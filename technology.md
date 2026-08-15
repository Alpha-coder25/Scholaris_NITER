# Technology Documentation

## 1. Stack Summary

| Layer | Technology | Reason |
|---|---|---|
| Backend framework | Django + Django REST Framework | Batteries-included, fast to build auth/RBAC/admin for a hackathon timeline, mature ORM fits a relational academic data model |
| Database | PostgreSQL via **Neon** (serverless Postgres, free tier) | Relational integrity for departments/courses/enrollments/exams; supports JSONB for flexible AI-question metadata; free tier means zero local DB setup for every team member, and the same connection string works in dev and in the deployed demo |
| Frontend | Django Templates + Tailwind CSS + HTMX/vanilla JS | Server-rendered pages are fastest to ship for a hackathon; HTMX handles partial-page interactivity (exam question advance, chat updates) without a full SPA framework |
| Real-time | Django Channels (WebSockets) | Chat, and optionally live exam-timer sync |
| Background tasks | Celery + Redis | Server-side exam timer enforcement, async AI calls, notification dispatch |
| AI | Anthropic API (Claude), server-side only | Question generation from uploaded material; never exposed client-side |
| File storage | Django `FileField` → local disk for hackathon demo, S3-compatible object storage for production | Lecture materials, submissions |
| Auth | Django's built-in auth + role field, session-based (JWT optional for API-only clients) | Fast to implement, sufficient for hackathon scope |

---

## 2. Backend Architecture

```mermaid
flowchart TB
    subgraph Client
        UI[Django Templates + Tailwind + HTMX/JS]
    end

    subgraph Server["Django Application Server"]
        URLs[URL Routing]
        Views[Views / DRF ViewSets]
        Perms[Role-Based Permission Layer]
        Models[Django ORM Models]
        Tasks[Celery Tasks]
    end

    subgraph Async["Background Workers"]
        Celery[Celery Worker]
        Redis[(Redis - broker + cache)]
    end

    subgraph Data
        PG[(PostgreSQL - Neon serverless, free tier)]
        FS[(File Storage: Materials/Submissions)]
    end

    subgraph External
        Claude[Anthropic API - Claude]
    end

    UI -->|HTTP/HTMX requests| URLs
    UI -->|WebSocket - chat, exam sync| Channels[Django Channels]
    URLs --> Views
    Views --> Perms
    Perms --> Models
    Models --> PG
    Views --> Tasks
    Tasks --> Celery
    Celery --> Redis
    Celery -->|question generation request| Claude
    Claude -->|draft questions JSON| Celery
    Celery --> Models
    Views --> FS
    Channels --> Redis
```

**Key architectural decisions:**
- **Role-based permission layer** sits between views and models — every query is scoped by the requesting user's role (Admin/Teacher/Student) and their department/course/enrollment relationships. No cross-department or cross-enrollment data leakage.
- **AI calls happen server-side only**, dispatched through Celery so the request/response cycle isn't blocked waiting on the Claude API, and so the API key never reaches the client.
- **Exam timer enforcement is server-authoritative** (detailed in §3) — the client UI reflects state, but does not decide it.

---

## 3. Exam Timer Enforcement — Workflow Diagram

This is the most technically distinctive part of the system, so it gets its own diagram.

```mermaid
sequenceDiagram
    participant S as Student Browser
    participant V as Django View/API
    participant DB as PostgreSQL (Neon)

    S->>V: Start Exam Attempt
    V->>DB: Create ExamAttempt(started_at=now)
    V->>DB: Create ExamAnswer(question=1, question_started_at=now)
    V-->>S: Serve Question 1 + per-question time_limit

    Note over S: Client shows countdown (UI only, not authoritative)

    alt Student submits before timeout
        S->>V: POST answer for Question 1
        V->>DB: Check now - question_started_at <= time_limit
        V->>DB: Save answer, mark question complete
    else Timer expires (client-side) or heartbeat poll
        S->>V: Heartbeat / auto-submit call
        V->>DB: Check now - question_started_at > time_limit
        V->>DB: Force-lock current answer as-is (or blank)
    end

    V->>DB: Check overall exam time (now - attempt.started_at) vs exam.duration
    alt Time remaining and questions remain
        V->>DB: Create ExamAnswer(question=N+1, question_started_at=now)
        V-->>S: Serve Question N+1
    else Time exhausted or last question done
        V->>DB: Mark ExamAttempt as submitted
        V-->>S: Show MCQ results (CQ pending)
    end
```

**Why this matters:** relying on client-side JavaScript alone for the countdown is not enforceable — a student can pause execution or tamper with local state. The server independently timestamps question start and validates elapsed time against the stored `time_limit` on every submission or heartbeat poll, so the true enforcement never depends on the client.

---

## 4. Hosted Database — Neon (Serverless Postgres, Free Tier)

The project uses [Neon](https://neon.tech) instead of a locally-installed Postgres instance:

- **One shared connection string** for the whole team and for the deployed demo — no one needs Postgres installed locally, which removes a whole class of "works on my machine" setup friction during the hackathon.
- **Free tier constraints to design around:**
  - **Scale-to-zero / cold start**: an idle Neon compute suspends after a period of inactivity; the first query after idle time incurs a short cold-start delay (roughly 1–2 seconds). This is a real risk for a *live* demo — see the mitigation in `development-plan.md`.
  - **Limited concurrent connections** on the free tier: Django's default persistent connections plus Celery workers can exhaust this quickly. Use Neon's **pooled connection string** (PgBouncer-backed, transaction-mode pooling) for the Django app and Celery workers, not the direct (unpooled) connection string.
  - **Branching** (a Neon feature): a database branch can be created per teammate or per feature if useful, but for hackathon speed the simplest setup is a single shared branch (`main`) for everyone.
- **Connection config**: `DATABASE_URL` is the Neon-provided pooled connection string, and requires `sslmode=require`. Handled via `dj-database-url` in `settings.py` — see `backend.md` §1.

## 5. Database Schema (PostgreSQL)

### 5.1 Entity-Relationship Overview

```mermaid
erDiagram
    DEPARTMENT ||--o{ COURSE : offers
    DEPARTMENT ||--o{ USER : belongs_to
    SEMESTER ||--o{ COURSE_OFFERING : has
    COURSE ||--o{ COURSE_OFFERING : offered_as
    USER ||--o{ COURSE_OFFERING : "teaches (Teacher)"
    USER ||--o{ ENROLLMENT : "enrolls (Student)"
    COURSE_OFFERING ||--o{ ENROLLMENT : has
    COURSE_OFFERING ||--o{ MATERIAL : contains
    COURSE_OFFERING ||--o{ ASSIGNMENT : has
    COURSE_OFFERING ||--o{ EXAM : has
    ASSIGNMENT ||--o{ SUBMISSION : receives
    USER ||--o{ SUBMISSION : "submits (Student)"
    EXAM ||--o{ EXAM_QUESTION : contains
    QUESTION ||--o{ EXAM_QUESTION : used_in
    COURSE_OFFERING ||--o{ QUESTION : "question bank of"
    EXAM ||--o{ EXAM_ATTEMPT : has
    USER ||--o{ EXAM_ATTEMPT : "attempts (Student)"
    EXAM_ATTEMPT ||--o{ EXAM_ANSWER : contains
    EXAM_QUESTION ||--o{ EXAM_ANSWER : answered_via
    COURSE_OFFERING ||--o{ RATING : receives
    USER ||--o{ RATING : "gives (Student)"
    USER ||--o{ RESEARCH_PROJECT : "supervises (Teacher)"
    USER ||--o{ RESEARCH_PROJECT : "authors (Student)"
    RESEARCH_PROJECT ||--o{ PUBLICATION : produces
```

### 5.2 Table Definitions

**`accounts_user`** (extends Django `AbstractUser`)
| Column | Type | Notes |
|---|---|---|
| id | UUID/PK | |
| role | varchar (`admin`, `teacher`, `student`) | |
| department_id | FK → department | nullable for institution-level admin |
| student_id_no / employee_id | varchar | NITER ID |
| created_at | timestamp | |

**`department`**
| id | PK |
| name | varchar (Textile Engineering, IPE, FDAE, CSE, EEE) |

**`semester`**
| id | PK |
| name | e.g. "Spring 2026" |
| start_date`, `end_date` | date |

**`course`**
| id | PK |
| department_id | FK |
| code`, `title`, `credit_hours` | |

**`course_offering`** *(a course taught in a specific semester by a specific teacher — this is the "admin assigns teacher" object)*
| id | PK |
| course_id | FK |
| semester_id | FK |
| teacher_id | FK → user |
| section | varchar, nullable |

**`enrollment`**
| id | PK |
| student_id | FK → user |
| course_offering_id | FK |
| registered_at | timestamp |

**`material`**
| id | PK |
| course_offering_id | FK |
| uploaded_by_id | FK → user |
| file`, `title`, `version`, `uploaded_at` | |

**`question`** *(question bank)*
| id | PK |
| course_offering_id | FK |
| type | (`mcq`, `cq`) |
| text | text |
| options | JSONB (MCQ only) |
| correct_answer | JSONB/text (MCQ only) |
| source | (`ai_generated`, `manual`) |
| approved_by_id | FK → user, nullable until teacher approves |
| created_at | timestamp |

**`exam`**
| id | PK |
| course_offering_id | FK |
| title | |
| total_duration_seconds | int |
| start_time`, `end_time` | timestamp |

**`exam_question`** *(ordered join table: exam ↔ question)*
| id | PK |
| exam_id | FK |
| question_id | FK |
| order | int |
| time_limit_seconds | int (per-question limit) |
| marks | int |

**`exam_attempt`**
| id | PK |
| exam_id | FK |
| student_id | FK → user |
| started_at`, `submitted_at` | timestamp |
| status | (`in_progress`, `submitted`, `graded`) |

**`exam_answer`**
| id | PK |
| attempt_id | FK → exam_attempt |
| exam_question_id | FK |
| question_started_at | timestamp *(server-set, for timer enforcement)* |
| answer_data | JSONB |
| auto_score | int, nullable (MCQ) |
| manual_score | int, nullable (CQ) |
| graded_by_id | FK → user, nullable |
| locked | boolean (true once timer expired or submitted) |

**`assignment`**
| id | PK |
| course_offering_id | FK |
| title`, `description`, `due_date` | |

**`submission`**
| id | PK |
| assignment_id | FK |
| student_id | FK → user |
| file/text | |
| status | (`submitted`, `accepted`, `refused`) |
| teacher_comment | text |
| submitted_at` | |

**`research_project`**
| id | PK |
| student_id | FK → user |
| supervisor_id | FK → user |
| title`, `stage` (`proposal`,`checkpoint`,`draft`,`final`,`published`) |
| status | (`pending`,`accepted`,`rejected`,`revision_requested`) |

**`research_stage_log`**
| id | PK |
| research_project_id | FK |
| stage`, `comment`, `changed_by_id`, `timestamp` |

**`publication`**
| id | PK |
| research_project_id | FK, nullable |
| title`, `venue`, `year`, `authors` (JSONB) |

**`rating`**
| id | PK |
| course_offering_id | FK |
| student_id | FK → user *(kept for integrity checks, not exposed in aggregate views)* |
| stars | int (1–5) |
| comment | text, nullable |
| created_at | timestamp |

**`notice`**
| id | PK |
| scope | (`institution`,`department`,`course_offering`) |
| scope_id | int, nullable |
| title`, `body`, `posted_by_id`, `created_at` |

**`chat_group`** / **`chat_message`**
| chat_group: id, course_offering_id (nullable for 1:1), type (`course_group`,`direct`) |
| chat_message: id, group_id, sender_id, body, sent_at |

---

## 6. Security & Data Scoping Notes

- All queries filtered through the permission layer by `request.user.role` + department/enrollment relationship — a student can never query another student's exam attempt or another course's materials.
- AI service layer receives **only the specific uploaded material** for a single generation request — not a student's broader academic record — to keep the data-privacy story simple and defensible.
- Ratings table stores `student_id` for anti-abuse/integrity purposes (e.g., one rating per student per course) but this is never surfaced in any teacher- or admin-facing view; only aggregates are exposed, and only once a minimum response count is met.
