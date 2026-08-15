# Development Plan — Hackathon Build

> **Status: BUILT AND LIVE.** This document is the original build plan; the MVP described below is implemented, deployed at https://scholaris-lime.vercel.app, and verified by 100/100 tests + 56/56 end-to-end checks. Beyond the original plan, the following were added during development and hardening: a public **landing page** with animated AI-exam-flow demo, **role-first sign-up** for students & teachers (NITER ID validation, department codes CS/EE/TE/FD/IP, auto batch), **admin People management** (CRUD + students grouped by year → department → section), **admin Syllabus management** (courses per department × semester, delete-blocked-when-assigned), the **Semester 1–8** term structure (two per year), removal of all published demo credentials, and a full **SQA pass (97/100)** with a CI workflow (`.github/workflows/ci.yml`).

## 1. Scope Boundary (Read This First)

Build **one complete, real, live-clickable loop**: the exam system, wrapped by the minimum surrounding modules needed to make it a coherent story. Everything else is a labeled roadmap slide, not a half-built screen. See `prd.md` §8 for the full scope rationale.

**In scope (build for real) — all ✅ done:**
1. ✅ Auth + role-based login (Admin/Teacher/Student) + **role-first self sign-up** for students & teachers
2. ✅ Admin: **People management** (add/view/edit all accounts) and **Syllabus management** (courses per department × semester) + assign teacher to course offering
3. ✅ Student: enroll in course
4. ✅ Teacher: upload material
5. ✅ AI: generate draft questions from material
6. ✅ Teacher: review/approve/edit questions, build exam (total + per-question timers), schedule
7. ✅ Student: take exam (one question at a time, server-enforced timers, auto-advance)
8. ✅ Grading: MCQ auto, CQ manual by teacher
9. ✅ Results: student + teacher views
10. ✅ Rating: student rates teacher (private aggregation)
11. ✅ Public landing page + per-role login guide + animated AI-exam-flow demo
12. ✅ Semester 1–8 structure (two semesters per year) across syllabus, assignment, and seed
13. ✅ SQA hardening: CI workflow, 100 tests, DAST/Load/Lighthouse passes, demo credentials removed

**Out of scope for live demo (wireframe/slide only):** research/thesis workflow, publication tracking, group chat, notice board, Phase 2 gap-analysis AI.

## 2. Suggested Team Split (4–5 people)

| Role | Responsibility |
|---|---|
| Backend Lead | Django models/migrations, permission layer, exam API + server-side timer enforcement (the highest-risk piece — start first) |
| Backend/AI | `ai_integration` service, Celery task for question generation, question review/approve endpoints |
| Frontend Lead | Templates + Tailwind shell, exam-taking screen + `exam_timer.js` (second-highest-risk piece) |
| Frontend/Full-stack | Admin assignment screens, teacher exam-builder UI, grading queue UI, results screens |
| (Optional 5th) | Rating module, demo data seeding, deployment, slide deck/demo script rehearsal |

## 3. Build Order & Timeline (assume a ~36–48hr hackathon window)

### Phase 0 — Setup (Hours 0–3)
- Repo, Django project skeleton, Tailwind build pipeline, base template/nav shell.
- Create the shared **Neon** project (free tier), grab the pooled connection string, drop it into `.env` for the whole team — no local Postgres install needed, so every teammate can `git clone` and be running against the same DB within minutes.
- Custom `User` model with `role` field; seed script for demo departments/users so nobody works against an empty DB.

### Phase 1 — Core Academic Skeleton (Hours 3–8)
- Models: Department, Semester, Course, CourseOffering, Enrollment.
- Admin: assign-teacher-to-course screen (functional CRUD, doesn't need to be pretty yet).
- Student: enroll-in-course screen.
- **Milestone check:** can an admin assign a teacher and a student enroll, end to end, through the UI? If not, do not move on.

### Phase 2 — Materials + Question Bank (Hours 8–14)
- Material upload (teacher).
- `Question` model + manual question creation (build this before AI — it's the fallback if AI integration runs late).
- Wire the Anthropic API call in `ai_integration/services.py`, Celery task, question-review screen (approve/edit/discard).
- **Milestone check:** teacher can upload a material and get back a list of AI-drafted questions they can approve.

### Phase 3 — Exam Build + Take (Hours 14–24) — **highest priority, highest risk**
- `Exam`, `ExamQuestion` (with per-question `time_limit_seconds`), `ExamAttempt`, `ExamAnswer` models.
- Exam builder UI: select questions, set total + per-question timers, schedule.
- Exam-take API: `start/`, `answer/`, `heartbeat/`, `submit/` — server-side timer validation is non-negotiable here, build and test it before polishing the UI.
- Exam-take frontend: single-question view + `exam_timer.js` (client display, server-authoritative behind it).
- **Milestone check:** run a full exam attempt yourself, let a question's timer expire on purpose, confirm the server force-advances and the answer locks. This is your core demo moment — do not skip testing the timeout path.

### Phase 4 — Grading + Results (Hours 24–30)
- MCQ auto-grade on submit.
- CQ grading queue UI for teacher.
- Results screens (student + teacher, including the per-question class breakdown).

### Phase 5 — Rating + Polish (Hours 30–36)
- Rating model + submission form + private aggregate view (admin/teacher).
- Visual polish pass on Tailwind styling, especially the exam screen (this is what's on camera longest).
- Seed realistic demo data (a real-looking course, a real-looking material, plausible AI-generated questions) so the live demo isn't running on placeholder text.

### Phase 6 — Demo Rehearsal + Buffer (Hours 36–48)
- Run the full demo script (below) at least 3 times end-to-end.
- Fix whatever breaks. Do not add new features in this window.
- Record the backup demo video (in case live demo/wifi fails).
- **Neon-specific step: wake the database 5–10 minutes before going on stage.** The free-tier compute auto-suspends after idle time, and the first query after suspend has a short cold-start delay — harmless normally, but an awkward pause during a live judging slot. Fire a few warm-up requests (e.g. load the admin dashboard) right before your slot to make sure the compute is already active.
- Finalize slides: problem → live demo → architecture/privacy slide → roadmap slide.

## 4. Demo Script (What You Actually Click)

1. **Admin panel** (10 sec): show teacher assigned to a course for the current semester.
2. **Teacher panel**: upload a lecture PDF → click "Generate Questions" → review the AI drafts on screen, approve a few, edit one → build an exam, set a short per-question timer (so the auto-advance is visible live) and total duration → schedule it.
3. **Student panel**: start the exam, answer Q1 normally, then **deliberately let Q2's timer run out on camera** so judges see the server-enforced auto-advance happen in real time. Finish the exam.
4. **Teacher panel**: grade the one CQ answer.
5. **Student panel**: show final results (MCQ + CQ combined) and per-question class breakdown on the teacher side.
6. **Student rates the teacher** → **Admin dashboard** shows the private aggregated rating.
7. Close on the architecture/privacy slide and the roadmap slide (`prd.md` §8, `technology.md` §5).

## 5. Definition of Done (for the hackathon submission)

- [x] All in-scope items in §1 work live, not mocked (verified by `verify_demo.py`, 56/56 checks).
- [x] Server-side timer enforcement demonstrably works (tested with a deliberate timeout).
- [x] Seeded demo data looks realistic, not like `test1`/`asdf` (5 departments, 8 semesters, realistic courses, students with NITER-format IDs/batches/sections).
- [x] Architecture diagram, DB schema, and privacy notes are in the submitted docs (`technology.md`).
- [ ] Demo video recorded as a fallback.
- [x] GitHub repo is clean, README has setup instructions that actually work from a fresh clone (auto-deploys to Vercel on push; CI green).

## 6. Explicit Cut List (if time runs short)

Cut in this order if you're behind schedule — do not cut anything above the line you've already reached:
1. Rating module (nice-to-have, not core to the exam story).
2. CQ grading UI polish (a plain list view is fine).
3. Manual question creation UI (keep only if AI integration is at risk of failing — otherwise AI-only is a fine demo).
4. Notice board (cut entirely if not started by Phase 4).

Never cut: the exam-taking flow, the server-side timer enforcement, or the AI question generation — these three are your differentiators.
