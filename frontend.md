# Frontend Documentation

## 1. Approach

Server-rendered **Django Templates + Tailwind CSS**, with **HTMX** (or light vanilla JS where HTMX doesn't fit) for the interactive pieces that need partial updates without a full page reload — chiefly the exam-taking flow and chat. This is the fastest path to a working, polished UI within a hackathon timeline, and it keeps the whole stack in Django rather than standing up a separate SPA build.

Where a genuinely dynamic client-side experience is needed (the exam question timer specifically), a small dedicated JS module is used instead of forcing HTMX to do something it's not suited for.

## 2. Structure

```
templates/
├── base.html                     # shared layout, Tailwind, nav by role
├── accounts/
│   └── login.html
├── admin/
│   ├── dashboard.html
│   ├── department_list.html
│   ├── course_offering_assign.html   # assign teacher to course/semester
│   └── analytics.html
├── teacher/
│   ├── dashboard.html
│   ├── course_detail.html
│   ├── material_upload.html
│   ├── question_review.html          # approve/edit AI-generated questions
│   ├── exam_builder.html             # select questions, set timers, schedule
│   ├── grading_queue.html            # grade CQ answers
│   └── research_supervision.html
├── student/
│   ├── dashboard.html
│   ├── course_detail.html
│   ├── exam_take.html                # single-question full-screen exam view
│   ├── exam_result.html
│   ├── research_submit.html
│   └── progress.html
├── chat/
│   └── chat_window.html
└── partials/                          # HTMX-swapped fragments
    ├── _question_card.html
    ├── _timer.html
    ├── _chat_message.html
    └── _notice_item.html

static/
├── css/
│   └── tailwind.css (built via Tailwind CLI/PostCSS)
└── js/
    ├── exam_timer.js                 # per-question + overall countdown, heartbeat polling
    ├── chat_socket.js                # WebSocket client for Channels
    └── htmx_config.js
```

## 3. Key Screens by Role

### Admin
- **Course Offering Assignment**: form to pick department → course → semester → teacher; table of current assignments.
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
  - On timer hit or explicit submit, the page auto-swaps (via HTMX or a controlled fetch) to the next question with a fresh timer.
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
- Exam screen intentionally minimal/high-contrast (large timer, large question text, no distracting nav) to read clearly on a projector during the live demo.

## 6. Chat (WebSocket client)

- `chat_socket.js` opens a WebSocket to the Channels consumer scoped to the current `course_offering` or direct-message thread; incoming messages appended via a small DOM update, outgoing messages sent over the same socket. No page reload needed.
