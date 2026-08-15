# Backend Documentation

## 1. Framework & Structure

Django project split into apps by domain, each with its own models/views/serializers/urls. This keeps the exam system (the MVP centerpiece) isolated and easy to develop/demo independently of less-critical modules.

```
scholaris/                  # project settings package (settings.py, urls.py, wsgi.py)
├── manage.py                 # repo root = Django project root (Vercel auto-detect)
├── scholaris/                # settings, root URLconf
├── accounts/                # custom User (role, batch, section), auth, role-first signup, admin People CRUD
├── academics/               # department, semester (1–8), course (+semester), course_offering, enrollment, syllabus CRUD
├── materials/               # versioned material uploads (+ extracted text cached in DB)
├── exams/                   # question bank, exam builder, exam engine, grading
│   └── services.py          # server-authoritative timer enforcement
├── ratings/                 # rating, private aggregation with threshold gating
├── ai_integration/          # Claude service + offline question generator
├── dashboard/               # role dashboards, course pages, admin analytics, seed commands
├── templates/               # Tailwind templates by role (incl. landing, admin users/students/syllabus)
├── static/                  # built CSS + exam_timer.js
├── loadtest/                # locustfile.py (load & stress)
├── dast_probe.py            # dynamic security probe (DAST)
├── verify_demo.py           # HTTP-level end-to-end regression (56 checks)
└── .github/workflows/ci.yml # tests + SAST + audits on every push
```

Modules from the original plan that were **cut or deferred** (roadmap only): `assignments`, `research`, `chat`, `notice`. Their features are not built in the MVP.

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

If `DATABASE_URL` is **unset**, the app falls back to a zero-config local **SQLite** database — a fresh clone runs with no external services.

**Notes specific to Neon's free tier:**
- Use Neon's **pooled connection string** (the one with `-pooler` in the hostname, PgBouncer transaction-mode pooling) for `DATABASE_URL` — both Django and Celery workers connect through it. The unpooled/direct connection string is only needed for tooling that requires session-level features (e.g. some migration operations), and should be reserved for the `manage.py migrate` step, not the running app.
- `conn_max_age=0` (i.e., don't let Django hold persistent connections open) is deliberate here — a serverless Postgres backend with a strict free-tier connection cap plays better with short-lived pooled connections than with Django's default connection reuse, especially once Celery workers are also connecting.
- Neon's compute **auto-suspends when idle**; the first query after a suspend period has a short cold-start delay. Not a code-level concern, but relevant to the demo — see `development-plan.md`.
- `sslmode=require` is mandatory — Neon rejects unencrypted connections.

## 2. App Responsibilities

| App | Responsibility |
|---|---|
| `accounts` | Custom `User` model (role, `batch`, `section`, `student_id_no`/`employee_id`), session auth, **role-first sign-up** (role selector → role-specific fields + NITER ID validation), role decorators, **admin People CRUD** (user directory, add/edit, password reset, students grouped by year → department → section) |
| `academics` | Department / Semester (1–8) / Course / CourseOffering / Enrollment; **admin Syllabus CRUD** (courses per department × semester, delete blocked when assigned); admin's teacher-assignment flow |
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

*Implementation note: these are Django **function-based views** returning JSON (no DRF viewsets in the MVP), guarded by role decorators (`@role_required('teacher')` etc.) rather than DRF permission classes. The permission model in §3 is unchanged in spirit.*

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
    Thin service layer — the exact code a Celery task would call, run
    synchronously so the app has zero external-service dependencies.
    Sends only the given material's extracted text to the Claude API
    (or the offline deterministic generator when ANTHROPIC_API_KEY is empty).
    Returns a structured JSON list of draft Question objects with source='ai_generated'
    and approved_by=None until a teacher reviews them.
    """
```
- Structured JSON output requested from the model (question text, type, options, correct answer for MCQ) — parsed and stored as `Question` rows with `source='ai_generated'`.
- Nothing is shown to students until `approved_by` is set by a teacher action.
- API key stored server-side only (environment variable), never sent to the client.
- **Offline fallback**: without an API key, a deterministic extractive generator builds draft questions from the material text — the full human-in-the-loop review flow demos with no network.

## 6. Background Jobs — intentionally none (no Celery/Redis)

The MVP deliberately has **no background workers**:
- **AI calls** run synchronously inside `ai_integration/services.py` (the code a Celery task would run). For a hackathon scale and the Neon free tier this removes the broker/worker operational burden entirely.
- **Exam timer enforcement** needs no beat task: on every answer submission, 5-second heartbeat, and page render the server recomputes elapsed time and locks/advances/finalises accordingly (`exams/services.py`). A student closing the tab cannot extend an exam — the next heartbeat or page load finalises it.

## 7. Real-Time Layer — not built (roadmap)

Chat (WebSockets / Django Channels) is roadmap-only and **not implemented** in the MVP. The exam countdown needs no WebSocket: `exam_timer.js` is display-only and all enforcement is server-side per §6.

## 8. Auth & Account Management

- Django **session auth** for the server-rendered app; sign-up logs the user in automatically.
- **Role-first sign-up** (`/accounts/signup/`): a role selector (Teacher/Student) then role-specific fields. Student IDs are validated as `CODE YYYYNNN` where the code must match the selected department (CS/EE/TE/FD/IP); duplicate usernames, student IDs, and employee IDs are rejected; batch auto-fills from the ID year.
- **No demo accounts / no published credentials**: seeded users receive random passwords printed once at seed time (`SEED_PASSWORD` env override for deterministic setups). The former one-click demo login (`?demo=`) was removed.
- **Admin People endpoints** (admin role only):
  - `GET/POST /accounts/admin/users/` — directory (filter by role/department) + add teacher/student
  - `GET/POST /accounts/admin/users/<id>/edit/` — update any account or reset a password (role is fixed for safety)
  - `GET /accounts/admin/students/` — students grouped by **year → department → section**
- **Admin Syllabus endpoints** (admin role only):
  - `GET /admin/syllabus/` — pick department + semester, list that term's courses
  - `POST /admin/syllabus/` — add course (duplicate in same semester rejected)
  - `POST /admin/syllabus/<id>/edit/` — update code/title/credits
  - `POST /admin/syllabus/<id>/delete/` — delete (blocked with a message if the course is assigned to an offering; `CourseOffering.course` is `PROTECT`)

## 9. Grading Logic

- **MCQ**: on `answer` submission, compare `answer_data` to `question.correct_answer`; set `auto_score` immediately.
- **CQ**: `auto_score` stays null; appears in the teacher's grading queue (`/api/course-offerings/{id}/grading-queue/`) until `manual_score` is set.
- Final score = sum of `auto_score` + `manual_score` across an attempt's answers; attempt status becomes `graded` once every CQ answer has a `manual_score`.
