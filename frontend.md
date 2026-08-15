# Frontend Documentation

## 1. Approach

Server-rendered **Django Templates + Tailwind CSS** with **vanilla JS** for the interactive pieces — no HTMX, no SPA framework. This is the fastest path to a working, polished UI within a hackathon timeline, and it keeps the whole stack in Django rather than standing up a separate build.

Small dedicated JS handles the genuinely dynamic bits: the exam question countdown (`exam_timer.js`, display-only — server enforcement described in `backend.md` §6), the role-first sign-up form toggle (show teacher vs. student fields), and the syllabus inline-edit row toggle.

## 2. Structure

```
templates/
├── base.html                     # shared layout, Tailwind, nav by role
├── dashboard/
│   ├── landing.html              # public landing page: what/how/roles + animated AI-exam-flow demo
│   ├── admin_dashboard.html      # institution dashboard
│   ├── teacher_dashboard.html
│   └── student_dashboard.html
├── accounts/
│   ├── login.html
│   └── signup.html               # role-first: selector → role-specific fields (vanilla JS toggle)
├── admin/
│   ├── users.html                # People directory (filter by role/dept) + add
│   ├── user_form.html            # add / edit teacher & student, password reset
│   ├── students.html             # students grouped by year → department → section
│   ├── syllabus.html             # dept + semester selector, course list with inline edit + delete
│   ├── course_offerings.html     # assign teacher to course/semester/section
│   └── analytics.html
├── teacher/
│   ├── dashboard.html
│   ├── course_detail.html
│   ├── material_upload.html
│   ├── question_review.html      # approve/edit AI-generated questions
│   ├── exam_builder.html         # select questions, set timers, schedule
│   └── grading_queue.html        # grade CQ answers
├── student/
│   ├── dashboard.html
│   ├── course_detail.html
│   ├── exam_take.html            # single-question full-screen exam view
│   └── exam_result.html

static/
├── css/
│   └── tailwind.css (built via Tailwind CLI, committed)
└── js/
    ├── exam_timer.js             # per-question + overall countdown, heartbeat polling
    └── signup.js                 # role toggle + ID/prefix helper (or inline in signup.html)
```

## 3. Key Screens by Role

### Public (no login)
- **Landing page** (served at `/`): what Scholaris is, how it works (three-step explainer), a per-role **login guide** (Admin / Teacher / Student), and an **animated demo of the AI exam flow** (material → AI drafts → teacher approves → exam → timer). Buttons: **Log in** / **Sign up**.
- **Role-first sign-up** (`/accounts/signup/`): "I am a…" selector (👨‍🏫 Teacher / 🎓 Student) reveals the matching fields. Students: name, username, email, department, **Student ID** (`CODE YYYYNNN`), batch (auto-fills from ID year), section. Teachers: name, username, email, department, Employee ID. Mismatched ID-prefix is rejected inline.

### Admin
- **People** (`/accounts/admin/users/`): directory of all teachers & students, filterable by role/department, add + edit per row (incl. password reset).
- **Students by cohort** (`/accounts/admin/students/`): student list grouped **year → department → section** with per-section tables and counts.
- **Syllabus** (`/admin/syllabus/`): department + semester (Semester 1–8) pickers; course table with inline edit and delete (blocked if assigned).
- **Course Offering Assignment**: form to pick department → course → semester → teacher → section; table of current assignments.
- **Analytics dashboard**: rating trend charts (aggregated only), research output counts, at-risk flags (Phase 2).

### Teacher
- **Course detail**: tabs for Materials / Assignments / Exams / Research / Chat, all scoped to that `course_offering`.
- **Question review**: list of AI-drafted questions with inline edit, Approve/Discard buttons, and a "add manual question" form (MCQ/CQ toggle).
- **Exam builder**: multi-select from approved question bank, per-question time-limit input next to each selected question, total-duration field, schedule datetime picker.
- **Grading queue**: one CQ answer at a time (or list view), marks input + comment, submit.

### Student
- **Exam-taking screen (core UX piece)**:
  - Full-screen single question, large visible per-question countdown (color shifts as it nears zero), overall exam progress/time in a smaller persistent header.
  - Answer input (MCQ = radio buttons, CQ = textarea).
  - No "back" button, no way to view other questions — enforced both visually and by the API only returning the current question.
  - On timer hit or explicit submit, the page auto-swaps (via a controlled fetch to the next-question endpoint) to the next question with a fresh timer.
- **Results screen**: MCQ score shown immediately, CQ marked "pending teacher review" until graded, then full score.
- **Progress dashboard**: attendance + assignment + exam performance in one view (Phase 2 adds AI gap-analysis on top of this same screen).

## 4. Exam Timer — Client Behavior (paired with server enforcement in `backend.md`)

```js
// static/js/exam_timer.js (simplified)
function startQuestionTimer(questionStartedAt, timeLimitSeconds, onExpire) {
  const deadline = new Date(questionStartedAt).getTime() + timeLimitSeconds * 1000;
  const interval = setInterval(() => {
    const remaining = deadline - Date.now();
    updateTimerDisplay(remaining);
    if (remaining <= 0) {
      clearInterval(interval);
      onExpire(); // triggers submit/advance call to server
    }
  }, 250);

  // Heartbeat: even if the tab is backgrounded, a periodic call lets the
  // server-authoritative check catch expiry independently of this client loop.
  setInterval(() => fetch(`/api/exam-attempts/${attemptId}/heartbeat/`, { method: 'POST' }), 5000);
}
```
This client timer is purely for **display and UX** (the visible countdown, color change, auto-advance trigger). The actual authority on whether an answer is still acceptable is the server check described in `backend.md` §4 — the client cannot extend or bypass a question's time limit.

## 5. Tailwind Usage Notes

- Shared design tokens (colors, spacing) defined once in `tailwind.config.js`; role-based nav bars use a consistent shell (`base.html`) with a distinct accent color per role (Admin/Teacher/Student) for quick visual orientation during the demo.
- The admin nav links: Dashboard · People · Students · Syllabus · Assign Courses · Analytics (the two new People/Students links were added with the account-management feature).
- An accessibility pass (Lighthouse) fixed low-contrast text (`text-slate-400` → `500/600`, `text-violet-500` → `600`) so the site scores **Accessibility 100** on the live deployment.
- Exam screen intentionally minimal/high-contrast (large timer, large question text, no distracting nav) to read clearly on a projector during the live demo.

## 6. Chat (WebSocket client)

- `chat_socket.js` opens a WebSocket to the Channels consumer scoped to the current `course_offering` or direct-message thread; incoming messages appended via a small DOM update, outgoing messages sent over the same socket. No page reload needed.
