# Backend Documentation

## 1. Framework & Structure

Django project split into apps by domain, each with its own models/views/serializers/urls. This keeps the exam system (the MVP centerpiece) isolated and easy to develop/demo independently of less-critical modules.

```
scholaris/
├── manage.py
├── scholaris/                  # project settings
│   ├── settings.py
│   ├── urls.py
│   ├── celery.py
│   └── asgi.py              # Channels entrypoint
├── accounts/                # custom User model, auth, roles
├── academics/                # department, semester, course, course_offering, enrollment, notice
├── materials/                # material uploads
├── exams/                    # question bank, exam, exam_attempt, exam_answer, grading
├── assignments/               # assignment, submission
├── research/                  # research_project, research_stage_log, publication
├── chat/                      # chat_group, chat_message, Channels consumers
├── ratings/                   # rating, aggregation logic
├── ai_integration/            # Claude API client, question-generation service
└── dashboard/                  # cross-app analytics views (admin/teacher/student dashboards)
```

### 1.1 Database Connection (Neon, Serverless Postgres)

The project connects to a **Neon** Postgres instance (free tier) rather than a locally-installed database. Configured via `dj-database-url` reading a single `DATABASE_URL` environment variable — the same variable works identically for local dev, CI, and the deployed demo.

```python
# scholaris/settings.py
import dj_database_url

DATABASES = {
    'default': dj_database_url.config(
        default=env('DATABASE_URL'),
        conn_max_age=0,       # important: see note below
        ssl_require=True,
    )
}
```

**Notes specific to Neon's free tier:**
- Use Neon's **pooled connection string** (the one with `-pooler` in the hostname, PgBouncer transaction-mode pooling) for `DATABASE_URL` — both Django and Celery workers connect through it. The unpooled/direct connection string is only needed for tooling that requires session-level features (e.g. some migration operations), and should be reserved for the `manage.py migrate` step, not the running app.
- `conn_max_age=0` (i.e., don't let Django hold persistent connections open) is deliberate here — a serverless Postgres backend with a strict free-tier connection cap plays better with short-lived pooled connections than with Django's default connection reuse, especially once Celery workers are also connecting.
- Neon's compute **auto-suspends when idle**; the first query after a suspend period has a short cold-start delay. Not a code-level concern, but relevant to the demo — see `development-plan.md`.
- `sslmode=require` is mandatory — Neon rejects unencrypted connections.

## 2. App Responsibilities

| App | Responsibility |
|---|---|
| `accounts` | Custom `User` model (role field), auth, permission classes (`IsAdmin`, `IsTeacher`, `IsStudent`, `IsEnrolledOrTeacher`) |
| `academics` | Department/Semester/Course/CourseOffering/Enrollment CRUD; admin's teacher-assignment flow; notices |
| `materials` | File upload/versioning, scoped access by enrollment |
| `exams` | Question bank, exam build/schedule, **exam-taking API with server-side timer enforcement**, auto-grading (MCQ), manual grading (CQ), gradebook |
| `assignments` | Assignment CRUD, submission accept/refuse workflow |
| `research` | Proposal submission, staged accept/reject/revision workflow, stage audit log |
| `chat` | WebSocket consumers (Django Channels) for 1:1 and course-group chat |
| `ratings` | Rating submission, aggregation with minimum-threshold gating |
| `ai_integration` | Thin service layer wrapping Anthropic API calls; called only from Celery tasks, never directly from a view |
| `dashboard` | Read-only aggregation views per role |

## 3. Permission Layer (Role-Based Access Control)

All views/viewsets use DRF permission classes layered on top of `IsAuthenticated`:

```python
class IsEnrolledOrTeacher(BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.role == 'admin':
            return True
        if user.role == 'teacher':
            return obj.course_offering.teacher_id == user.id
        if user.role == 'student':
            return obj.course_offering.enrollment_set.filter(student=user).exists()
        return False
```

Every model that hangs off a `course_offering` (materials, exams, assignments, questions) is checked this way — no query ever crosses a department/enrollment boundary implicitly.

## 4. Exam System — API Design (MVP Core)

| Endpoint | Method | Role | Purpose |
|---|---|---|---|
| `/api/course-offerings/{id}/materials/` | POST | Teacher | Upload material |
| `/api/course-offerings/{id}/generate-questions/` | POST | Teacher | Trigger AI generation (async, Celery) from a material |
| `/api/course-offerings/{id}/questions/` | GET/PATCH | Teacher | Review/edit/approve/discard AI-drafted or manual questions |
| `/api/course-offerings/{id}/exams/` | POST | Teacher | Build exam: select approved questions, set total + per-question durations, schedule |
| `/api/exams/{id}/start/` | POST | Student | Begin `ExamAttempt`, server timestamps `started_at`, serves Question 1 with `question_started_at` |
| `/api/exam-attempts/{id}/answer/` | POST | Student | Submit answer for current question; server validates `now - question_started_at <= time_limit` before accepting; on timeout (via this call or a heartbeat) locks answer and returns next question |
| `/api/exam-attempts/{id}/heartbeat/` | POST | Student | Periodic poll (e.g. every 5s) so the server can force-advance even if the student never submits (covers "student walks away" case) |
| `/api/exam-attempts/{id}/submit/` | POST | Student/System | Finalize attempt when questions exhausted or overall timer hit |
| `/api/exam-attempts/{id}/grade/` | POST | Teacher | Submit CQ marks + comment per answer |
| `/api/exam-attempts/{id}/results/` | GET | Student/Teacher | MCQ score instantly; full score once CQ graded; teacher sees per-question class breakdown |

### Server-side timer enforcement (critical detail)
- `question_started_at` is set by the **server**, never trusted from the client.
- On every answer submission or heartbeat, the server computes elapsed time and compares it against `exam_question.time_limit_seconds`.
- If elapsed time exceeds the limit, the server locks the current answer (whatever was submitted, or blank) and advances the attempt pointer — the client UI reflects this but does not decide it.
- A Celery beat task also sweeps `in_progress` attempts periodically as a safety net for students who close the tab without a final heartbeat, so exams still terminate correctly.

## 5. AI Integration Service

```python
# ai_integration/services.py
def generate_questions_from_material(material, num_mcq=5, num_cq=2):
    """
    Called only from a Celery task, never directly from a request/response cycle.
    Sends only the given material's extracted text to the Claude API.
    Returns a structured JSON list of draft Question objects with source='ai_generated'
    and approved_by=None until a teacher reviews them.
    """
```
- Structured JSON output requested from the model (question text, type, options, correct answer for MCQ) — parsed and stored as `Question` rows with `source='ai_generated'`.
- Nothing is shown to students until `approved_by` is set by a teacher action.
- API key stored server-side only (environment variable), never sent to the client.

## 6. Background Jobs (Celery + Redis)

| Task | Trigger | Purpose |
|---|---|---|
| `generate_questions_task` | Teacher clicks "Generate Questions" | Async call to Claude API, avoids blocking the request |
| `sweep_expired_exam_attempts` | Celery beat, every N seconds | Force-submits attempts whose overall exam timer has lapsed without a final client call |
| `notify_new_material` / `notify_new_assignment` | On material/assignment creation | Pushes a notice/notification |

## 7. Real-Time Layer (Django Channels)

- `chat/consumers.py`: `CourseGroupConsumer` (scoped to a `course_offering`'s enrolled students + teacher) and `DirectMessageConsumer` (1:1).
- Redis as the channel layer backend (shared with Celery broker for simplicity in the hackathon build).

## 8. Auth

- Django session auth for the server-rendered app (simplest for a Django-templates + HTMX frontend).
- DRF token/JWT auth kept available on the same endpoints for any future mobile client, without changing the permission layer.

## 9. Grading Logic

- **MCQ**: on `answer` submission, compare `answer_data` to `question.correct_answer`; set `auto_score` immediately.
- **CQ**: `auto_score` stays null; appears in the teacher's grading queue (`/api/course-offerings/{id}/grading-queue/`) until `manual_score` is set.
- Final score = sum of `auto_score` + `manual_score` across an attempt's answers; attempt status becomes `graded` once every CQ answer has a `manual_score`.
