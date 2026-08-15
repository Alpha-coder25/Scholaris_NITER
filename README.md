# Scholaris

**NITER's EMS only tracks attendance. Scholaris is where academics, exams, and research actually happen.**

A unified academic and research management platform built for NITER's real structure — 5 departments, a closed-credit bi-semester system, and the full lifecycle of courses, exams, research, and faculty–student interaction.

Built for **NITER Innovate Hackathon 2026** (Academic track). Full product thinking in [`prd.md`](./prd.md), architecture in [`technology.md`](./technology.md), API/permission design in [`backend.md`](./backend.md), UI plan in [`frontend.md`](./frontend.md), build plan & demo script in [`development-plan.md`](./development-plan.md).

---

## The problem

Course materials, assignments, exams, research supervision, publications, faculty–student communication, and course-quality feedback all happen **outside** NITER's EMS — over email, Facebook groups, and paper. No central record, no analytics, no audit trail.

## The MVP (what is built and works)

The live demo is the **exam system end-to-end**, wrapped in the minimum surrounding modules that make it a real story:

1. ✅ Role-based auth (Admin / Teacher / Student)
2. ✅ Admin assigns a teacher to a course offering
3. ✅ Student enrolls in a course
4. ✅ Teacher uploads lecture materials (versioned)
5. ✅ **AI drafts questions from the material — teacher must review & approve (human-in-the-loop)**
6. ✅ Exam builder: pick approved questions, set per-question timers + marks, schedule the window
7. ✅ Student takes the exam: one question at a time, **server-enforced timers**, auto-advance, no backtracking
8. ✅ Grading: MCQ auto-graded instantly, CQ queued for the teacher
9. ✅ Results: student score + teacher gradebook with per-question class analytics
10. ✅ Faculty ratings — private, aggregated, threshold-gated

**Roadmap only (not built for the demo):** research/thesis workflow, publications, group chat, assignments module, notice board, Phase-2 gap-analysis AI. See `development-plan.md` §1.

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Django 6 + DRF | Custom `User` with `role` field; function-based views + JSON API for the exam engine |
| Database | PostgreSQL via **Neon** (serverless) | `DATABASE_URL` in `.env`; falls back to **SQLite** with zero config if unset |
| Frontend | Django Templates + Tailwind CSS + vanilla JS | Exam screen is a dedicated minimal page + `exam_timer.js` |
| AI | Anthropic API (Claude) | Server-side only; **offline fallback generator** when no API key is set |
| Deploy | **Vercel** | Auto-detected Django (`manage.py` + `requirements.txt` at repo root); shared Neon DB |

**Implementation notes (vs. the original plan):**
- **No Celery/Redis dependency.** The AI call runs synchronously behind a thin service layer (`ai_integration/services.py`) — the exact code a Celery task would call — so the app runs from a fresh clone with no external services. Same for exam sweeps: enforcement happens server-side on every answer/heartbeat/render, which is the actual requirement.
- **AI works offline.** If `ANTHROPIC_API_KEY` is empty, a deterministic extractive generator builds draft questions from the material text, so the full human-in-the-loop review flow is demoable without network/API key.
- **Serverless-safe materials.** Extracted material text is stored in the database (`Material.content_text`), so AI question generation works even though uploaded files live on ephemeral disk on Vercel.

## Quick start

```bash
# 1. Python environment (repo root)
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Environment — the repo ships a working .env pointed at the shared Neon
#    PostgreSQL database (same DB the deployed app uses). To go database-less,
#    delete .env and the app falls back to local SQLite.
#    Optional: add ANTHROPIC_API_KEY for real AI question generation.

# 3. Migrate + seed demo data (departments, users, courses, materials,
#    question bank, a live exam, ratings)
python manage.py migrate
python manage.py seed_demo_data

# 4. Tailwind (built CSS is committed, so this is only needed when restyling)
npm install
npm run build:css                  # or: npm run watch:css

# 5. Run
python manage.py runserver
```

Open http://localhost:8000 — the root serves a **public landing page** (what Scholaris is, how it works, per-role login guide) with **Log in** and **Sign up as a student** buttons. Logged-in users land directly on their role dashboard; logging out returns to the landing page.

### Accounts

There are **no published demo credentials.** `seed_demo_data` gives every
seeded user a strong random password and prints the full list once at seed
time — save it if you need to log in as a seeded user. For deterministic
setups (CI, a shared demo DB), set `SEED_PASSWORD` in the environment and all
seeded users share that password.

Students can **sign up themselves** (`/accounts/signup/`) — they get a `student`
account, are logged in automatically, and can then enroll in courses. Teacher
and admin accounts are created by the institution (the admin can also create
them, or a superuser can be made via `createsuperuser`).

## Demo script (60–90 seconds)

1. **Admin** → dashboard shows the seeded course assignments → *Analytics* shows private aggregated ratings.
2. **Teacher** → open *Data Structures* → upload a lecture (or use the seeded one) → **✨ Generate questions** → AI drafts appear in the bank → approve a few, discard one, edit one → **Build exam** with a short per-question timer (e.g. 20s) → schedule.
3. **Student** → enroll (or use seeded enrollment) → start *Midterm 1* → answer Q1 normally, then **deliberately let Q2's timer expire on camera** — the server force-advances and locks the answer → finish the exam → MCQ score shows instantly.
4. **Teacher** → *Grading queue* → grade the CQ answer → *Gradebook* shows per-question class analytics.
5. **Student** → full results → rate the teacher.
6. **Admin** → Analytics shows the aggregated rating (only past the 3-response threshold — privacy by design).

Full rehearsal plan: `development-plan.md` §4. If you're on Neon, hit the app a few minutes before demo time to avoid the free-tier cold start.

## How the exam timers really work

- The **server** writes `ExamAttempt.started_at` and `ExamAnswer.question_started_at` — never the client.
- On every answer submission, 5-second heartbeat, or page render, the server recomputes elapsed time against the stored per-question limit and overall duration, then locks/advances/finalises accordingly. A student cannot extend a deadline by pausing JS, tampering with local state, or reloading.
- The client countdown (`static/js/exam_timer.js`) is **display only**. Closing the tab cannot pause the exam — the next heartbeat (or page load) finalises it server-side.

## Project structure (repo root = Django project root)

```
.
├── manage.py            # Vercel/Heroku auto-detect here
├── requirements.txt
├── .env                 # DATABASE_URL (Neon pooled) + SECRET_KEY — gitignored
├── scholaris/           # settings package (settings.py, urls.py, wsgi.py)
├── accounts/            # custom User (role), login, role decorators
├── academics/           # department, semester, course, offering, enrollment
├── materials/           # versioned material uploads (+ DB-cached text)
├── exams/               # question bank, exam builder, exam engine, grading
│   └── services.py      # server-authoritative timer enforcement
├── ratings/             # private, aggregated faculty ratings
├── ai_integration/      # Claude service + offline question generator
├── dashboard/           # role dashboards, course pages, admin analytics, seed command
├── templates/           # Tailwind templates by role
├── static/              # built CSS + exam_timer.js
├── verify_demo.py       # HTTP-level end-to-end test of all 10 MVP flows (43 checks)
├── prd.md, technology.md, backend.md, frontend.md, development-plan.md
└── README.md
```

## Deploy to Vercel

**Live: https://scholaris-lime.vercel.app** (already deployed, connected to GitHub — pushes to `main` auto-deploy).

> The clean `scholaris.vercel.app` is already taken globally, so Vercel assigned
> `scholaris-lime.vercel.app` for this project. "Use only Scholaris" — no other
> domains are attached; you can point a custom domain at the project later if you own one.

The project is configured for Vercel's Django support (auto-detect via `manage.py`, auto-install of `requirements.txt`, automatic `collectstatic`, Python 3.12 pinned in `.python-version`).

Project env vars already set (production + preview):

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon **pooled** connection string (same as local `.env`) |
| `SECRET_KEY` | random key (same as local `.env`) |
| `DEBUG` | `0` |

Deploying / re-deploying:
- The GitHub repo is connected, so **pushing to `main` auto-deploys**.
- Or from the CLI: `vercel --prod` (Vercel CLI must be logged in).
- Migrations are **not** run automatically — run them once against the shared DB (they hit the Neon DB via your local `.env`; the deployed app reads the same data):
  ```bash
  python manage.py migrate
  python manage.py seed_demo_data
  ```

**Notes**
- One DB, everywhere: local dev and the Vercel deployment share the Neon database, so seeded data works identically on the live site. There are no published demo accounts — seeded users get random passwords printed once at seed time (or `SEED_PASSWORD` for deterministic setups).
- Uploaded material *files* are ephemeral on serverless disk; extracted text is stored in the DB so AI generation always works. For a persistent file store, add S3-compatible storage later.
- Free-tier Neon cold-starts after idle — hit the app a few minutes before a live demo.

## Resetting the demo data

```bash
python manage.py reset_demo_data         # flush + reseed, asks for confirmation
python manage.py reset_demo_data --yes   # non-interactive (CI / before a live demo)
```

Restores the shared DB to the exact seeded state (12 demo users, 5 offerings, question bank, 1 live exam, 6 ratings). Use the **direct** (non-pooled) Neon connection string for this maintenance command if the pooled connection drops mid-flush.

## Verification

```bash
python -c "import verify_demo"     # runs every MVP flow through Django's test client
```

Covers: role-based access control, admin assignment, enrollment, material upload, AI generation → approval, exam build, exam-taking with **deliberate timer expiry** and heartbeat walk-away, MCQ auto-grade, CQ manual grade, results, gradebook analytics, and threshold-gated rating aggregation.

## Documentation

| File | Contents |
|---|---|
| [`prd.md`](./prd.md) | Product requirements, feature analysis, role workflows |
| [`technology.md`](./technology.md) | Architecture, exam-timer sequence, database schema |
| [`backend.md`](./backend.md) | App structure, API design, permission model |
| [`frontend.md`](./frontend.md) | Screen breakdown, exam timer client behaviour |
| [`development-plan.md`](./development-plan.md) | Build order, timeline, demo script, cut list |
