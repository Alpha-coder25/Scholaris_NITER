# Scholaris

**NITER's EMS only tracks attendance. Scholaris is where academics, research, and communication actually happen.**

A unified academic and research management platform built for NITER's real structure: 5 departments, a closed-credit bi-semester system, and the full lifecycle of courses, exams, research, and faculty-student interaction — not just attendance.

Built for NITER Innovate Hackathon 2026 ("Be The Solution") — Academic track.

---

## Problem

NITER's existing EMS is used almost exclusively for attendance. Course materials, assignments, exams, research/thesis supervision, publication tracking, faculty-student communication, and course-quality feedback all happen outside of it — over email, informal group chats, and paper — with no central record, no analytics, and no scalability.

Full problem analysis: [`prd.md`](./prd.md)

## Solution

Scholaris gives Admins, Teachers, and Students one platform for:
- Academic program management (department/semester/course, teacher-to-course assignment, student enrollment)
- Course materials
- Assignments (submit → accept/refuse)
- **AI-assisted online exams** with per-question timers, server-enforced auto-advance, MCQ auto-grading, and CQ manual grading
- Research & thesis supervision (staged proposal → checkpoint → draft → publication workflow)
- Official 1:1 and group chat
- Private, aggregated faculty ratings

## MVP Built for This Hackathon

The live demo centers on the **exam system end-to-end**: Admin assigns a course → Student enrolls → Teacher uploads material → AI drafts questions → Teacher approves and builds a timed exam → Student takes it with per-question, server-enforced timers → MCQ auto-grades, CQ is graded by the teacher → both see results → student rates the teacher.

Full scope and build plan: [`development-plan.md`](./development-plan.md)

## Tech Stack

- **Backend:** Django + Django REST Framework
- **Database:** PostgreSQL via [Neon](https://neon.tech) (serverless Postgres, free tier)
- **Frontend:** Django Templates + Tailwind CSS + HTMX
- **Real-time:** Django Channels (WebSockets) for chat
- **Background jobs:** Celery + Redis (AI calls, server-side exam timer enforcement)
- **AI:** Anthropic API (Claude) — question generation from uploaded materials, human-approved before use

Full architecture and database schema: [`technology.md`](./technology.md)
Backend details: [`backend.md`](./backend.md)
Frontend details: [`frontend.md`](./frontend.md)

## Project Structure

```
scholaris/
├── accounts/          # custom User model, auth, roles
├── academics/         # department, semester, course, enrollment, notices
├── materials/          # lecture material uploads
├── exams/              # question bank, exam builder, timed exam engine, grading
├── assignments/          # assignment + submission workflow
├── research/              # research/thesis supervision workflow
├── chat/                    # WebSocket-based official chat
├── ratings/                 # private/aggregated faculty ratings
├── ai_integration/           # Claude API service layer
├── dashboard/                 # role-based analytics views
├── templates/                  # Django templates (Tailwind)
└── static/                      # Tailwind CSS + JS (exam timer, chat client)
```

## Setup

```bash
# clone
git clone <repo-url>
cd scholaris

# python env
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# database (Neon — serverless Postgres, free tier)
# 1. create a free project at https://neon.tech
# 2. copy the *pooled* connection string (hostname contains "-pooler")
# 3. paste it into .env as DATABASE_URL — no local Postgres install needed

# environment variables
cp .env.example .env            # set DATABASE_URL (Neon pooled string), ANTHROPIC_API_KEY, REDIS_URL, SECRET_KEY

python manage.py migrate
python manage.py seed_demo_data   # loads sample departments/courses/users for demo

# tailwind
npm install
npm run build:css                # or `npm run watch:css` during development

# run
redis-server &
celery -A scholaris worker -l info &
python manage.py runserver
```

Visit `http://localhost:8000`. Seeded demo logins are listed in `accounts/fixtures/demo_users.json`.

## Documentation

| File | Contents |
|---|---|
| [`prd.md`](./prd.md) | Full product requirements, feature analysis, role workflows |
| [`technology.md`](./technology.md) | Backend architecture, exam-timer workflow, database schema |
| [`backend.md`](./backend.md) | Django app structure, API design, permission model |
| [`frontend.md`](./frontend.md) | Template structure, screen breakdown, exam timer client behavior |
| [`development-plan.md`](./development-plan.md) | Hackathon build plan, timeline, demo script |

## Team

*(add team member names/roles here)*

## License

*(add license here, e.g. MIT — confirm hackathon submission requirements first)*
