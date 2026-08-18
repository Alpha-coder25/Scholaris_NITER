"""
AI integration services.

All AI features follow Scholaris's human-in-the-loop philosophy:
  * AI drafts, humans approve — never autonomous.
  * Server-only — API key never reaches the client.
  * Minimal data — only the specific material/answer needed for the task.
  * Offline fallback — every feature works without an API key.

In production this is dispatched via a background worker (Celery) so the
request/response cycle is never blocked on the AI API. For the hackathon build
it runs synchronously behind a thin service layer, so the exact same code path
can move into a Celery task later without touching the views.
"""
import csv
import io
import json
import random
import re
import time
from collections import defaultdict
from decimal import Decimal

from django.conf import settings

from exams.models import Question

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
def extract_text(file_obj):
    """Extract readable text from an uploaded material (PDF, TXT, MD)."""
    name = (file_obj.name or "").lower()
    if name.endswith(".pdf"):
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(file_obj)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""
    try:
        return file_obj.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Anthropic-backed generation
# ---------------------------------------------------------------------------
def _generate_with_anthropic(material_text, num_mcq=5, num_cq=2):
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    prompt = f"""You are an expert university lecturer generating assessment questions.

Based ONLY on the following lecture material, draft exactly {num_mcq} multiple-choice
questions and {num_cq} constructed-response (written) questions suitable for an
undergraduate exam. Questions must be answerable from the material.

Return STRICT JSON matching this schema — no markdown, no commentary:
{{
  "questions": [
    {{
      "type": "mcq",
      "text": "question text",
      "options": ["option A", "option B", "option C", "option D"],
      "correct_index": 0,
      "answer_explanation": "short justification"
    }},
    {{
      "type": "cq",
      "text": "question text",
      "reference_answer": "model answer outline"
    }}
  ]
}}

LECTURE MATERIAL:
---START---
{material_text[:12000]}
---END---"""

    message = client.messages.create(
        model=settings.AI_MODEL,
        max_tokens=4096,
        temperature=0.4,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(raw)

    drafts = []
    for item in data.get("questions", []):
        if item.get("type") == "mcq":
            options = item.get("options", [])
            if len(options) < 2:
                continue
            drafts.append(
                {
                    "type": "mcq",
                    "text": item["text"],
                    "options": options,
                    "correct_answer": item.get("correct_index", 0),
                    "explanation": item.get("answer_explanation", ""),
                }
            )
        else:
            drafts.append(
                {
                    "type": "cq",
                    "text": item["text"],
                    "reference_answer": item.get("reference_answer", ""),
                }
            )
    return drafts


# ---------------------------------------------------------------------------
# Offline fallback generator (works without an API key)
# ---------------------------------------------------------------------------
def _generate_offline(material_text, num_mcq=5, num_cq=2):
    """Deterministic extractive generator — real sentences from the material
    turned into questions, so the human-in-the-loop review flow is demoable
    even with no network/API key."""
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", material_text)
        if len(s.strip()) > 40
    ]
    if len(sentences) < 4:
        sentences = [
            s.strip() for s in material_text.splitlines() if len(s.strip()) > 20
        ]
    sentences = sentences[:max(6, num_mcq)]

    drafts = []
    correct = sentences[0] if sentences else ""

    # MCQ: "which sentence best captures X" using a topic noun from the correct one.
    for i, sent in enumerate(sentences[:num_mcq]):
        others = [s for s in sentences if s != sent][:3]
        while len(others) < 3 and len(sentences) > 3:
            others.append(sentences[(i + len(others) + 1) % len(sentences)])
        while len(others) < 3:
            others.append("The material does not discuss this point.")
        options = others[:3] + [sent]
        # nosec B311 -- shuffle is for display variety of MCQ options in the
        # offline demo generator only; nothing security-related depends on it.
        random.Random(42 + i).shuffle(options)  # nosec B311
        topic = _topic_of(sent)
        drafts.append(
            {
                "type": "mcq",
                "text": f"Which of the following statements about “{topic}” is correct, according to the lecture material?",
                "options": options,
                "correct_answer": options.index(sent),
                "explanation": "Directly supported by the lecture material.",
            }
        )

    # CQ: explain / summarise prompts on real sentences.
    cq_sources = sentences[1 : 1 + num_cq] if len(sentences) > 1 else sentences[:1]
    for sent in cq_sources:
        drafts.append(
            {
                "type": "cq",
                "text": f"Explain the following statement from the lecture material in your own words, and give one example: “{sent}”",
                "reference_answer": sent,
            }
        )
    return drafts


def _topic_of(sentence):
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", sentence)
    stop = {"the", "this", "that", "with", "from", "into", "have", "been", "they",
            "their", "which", "when", "where", "what", "will", "would", "should",
            "could", "there", "these", "those", "than", "then", "also", "such",
            "its", "are", "was", "were", "not", "for", "and", "but", "has"}
    for w in words:
        if w.lower() not in stop:
            return w
    return "this topic"


# ---------------------------------------------------------------------------
# Usage logging
# ---------------------------------------------------------------------------
def _log_usage(feature, status, latency_ms=0, input_tokens=0, output_tokens=0,
              error_message="", model_used="", metadata=None):
    """Log an AI usage event for observability and cost tracking."""
    from .models import AIUsageLog
    AIUsageLog.objects.create(
        feature=feature,
        status=status,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error_message=error_message,
        model_used=model_used or getattr(settings, "AI_MODEL", ""),
        metadata=metadata or {},
    )


def _timed_anthropic_call(prompt, feature):
    """Call Anthropic API with timing and usage logging. Returns (raw_text, tokens)."""
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    start = time.time()
    message = client.messages.create(
        model=settings.AI_MODEL,
        max_tokens=4096,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )
    latency = int((time.time() - start) * 1000)
    raw = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    _log_usage(
        feature=feature,
        status="success",
        latency_ms=latency,
        input_tokens=getattr(message.usage, "input_tokens", 0),
        output_tokens=getattr(message.usage, "output_tokens", 0),
    )
    return raw


# ---------------------------------------------------------------------------
# Public API — Question Generation
# ---------------------------------------------------------------------------
def generate_questions(material):
    """Generate draft questions from a Material. Returns a list of draft dicts.

    Prefers the Anthropic API; falls back to the offline generator when no
    ANTHROPIC_API_KEY is configured or the API call fails.
    """
    material_text = material.content_text or extract_text(material.file)
    if not material_text.strip():
        material_text = f"{material.title}. This lecture material covers the core "
        f"concepts of {material.title} for the course."

    used_ai = False
    if settings.ANTHROPIC_API_KEY and anthropic is not None:
        try:
            drafts = _generate_with_anthropic(material_text)
            used_ai = True
        except Exception as exc:
            _log_usage(
                feature="question_generation",
                status="error",
                error_message=str(exc)[:500],
            )
            drafts = None
    if not used_ai:
        drafts = _generate_offline(material_text)
        if not used_ai and settings.ANTHROPIC_API_KEY:
            pass  # error already logged above
        else:
            _log_usage(feature="question_generation", status="fallback")

    return drafts, used_ai


def create_draft_questions(course_offering, drafts):
    """Persist generated drafts as Question rows with source='ai_generated'
    and status='draft' — never visible to students until approved."""
    created = []
    for d in drafts:
        created.append(
            Question.objects.create(
                course_offering=course_offering,
                type=d["type"],
                text=d["text"],
                options=d.get("options", []),
                correct_answer=(
                    d.get("correct_answer")
                    if d["type"] == "mcq"
                    else d.get("reference_answer", "")
                ),
                source="ai_generated",
                status="draft",
                approved_by=None,
            )
        )
    return created


def generation_source_label(used_ai):
    if used_ai:
        return "Anthropic Claude (AI)"
    return "built-in offline generator (no API key configured)"


# ---------------------------------------------------------------------------
# Public API — Student Progress & Gap Analysis
# ---------------------------------------------------------------------------
def analyze_student_progress(course_offering):
    """Analyze all students' exam performance in a course offering.

    Returns a dict with:
      - topic_summary: per-topic class-wide stats
      - student_gaps: per-student weak-topic flags
      - class_overview: aggregate metrics

    This is a purely analytical function — it reads existing exam data and
    produces insights. No AI API call is needed for the quantitative part;
    the AI enhances the analysis with natural-language insights when available.
    """
    from exams.models import ExamAnswer, ExamQuestion

    # Gather all graded answers for this offering
    answers = ExamAnswer.objects.filter(
        attempt__exam__course_offering=course_offering,
        submitted_at__isnull=False,
    ).select_related(
        "attempt", "attempt__student", "exam_question", "exam_question__question"
    )

    if not answers:
        return {
            "topic_summary": [],
            "student_gaps": [],
            "class_overview": {
                "total_students": 0,
                "total_exams": 0,
                "avg_score_pct": 0,
            },
        }

    # Group by question topic (extracted from question text)
    topic_stats = defaultdict(lambda: {
        "total": 0, "correct": 0, "total_marks": 0, "earned_marks": 0
    })
    student_stats = defaultdict(lambda: {
        "total": 0, "correct": 0, "total_marks": 0, "earned_marks": 0,
        "topic_details": defaultdict(lambda: {"total": 0, "correct": 0, "earned": 0, "possible": 0})
    })

    for ans in answers:
        q = ans.exam_question.question
        eq = ans.exam_question
        topic = _extract_topic(q.text)
        score = ans.auto_score or 0
        is_correct = score > 0 if q.type == "mcq" else (ans.manual_score is not None and ans.manual_score > 0)
        marks_earned = score if q.type == "mcq" else (ans.manual_score or 0)
        marks_possible = eq.marks

        # Topic aggregation
        topic_stats[topic]["total"] += 1
        if is_correct:
            topic_stats[topic]["correct"] += 1
        topic_stats[topic]["total_marks"] += marks_possible
        topic_stats[topic]["earned_marks"] += marks_earned

        # Student aggregation
        s = ans.attempt.student_id
        student_stats[s]["total"] += 1
        if is_correct:
            student_stats[s]["correct"] += 1
        student_stats[s]["total_marks"] += marks_possible
        student_stats[s]["earned_marks"] += marks_earned
        student_stats[s]["topic_details"][topic]["total"] += 1
        if is_correct:
            student_stats[s]["topic_details"][topic]["correct"] += 1
        student_stats[s]["topic_details"][topic]["earned"] += marks_earned
        student_stats[s]["topic_details"][topic]["possible"] += marks_possible

    # Build topic summary
    topic_summary = []
    for topic, s in sorted(topic_stats.items(), key=lambda x: x[1]["earned_marks"] / max(x[1]["total_marks"], 1)):
        pct = round(100 * s["correct"] / s["total"], 1) if s["total"] else 0
        topic_summary.append({
            "topic": topic,
            "total_answers": s["total"],
            "correct": s["correct"],
            "accuracy_pct": pct,
            "score_pct": round(100 * s["earned_marks"] / s["total_marks"], 1) if s["total_marks"] else 0,
        })

    # Build student gap analysis
    student_gaps = []
    for student_id, s in student_stats.items():
        overall_pct = round(100 * s["correct"] / s["total"], 1) if s["total"] else 0
        weak_topics = []
        strong_topics = []
        for topic, td in s["topic_details"].items():
            t_pct = round(100 * td["correct"] / td["total"], 1) if td["total"] else 0
            if t_pct < 50:
                weak_topics.append({"topic": topic, "accuracy_pct": t_pct})
            elif t_pct >= 80:
                strong_topics.append({"topic": topic, "accuracy_pct": t_pct})
        weak_topics.sort(key=lambda x: x["accuracy_pct"])
        strong_topics.sort(key=lambda x: -x["accuracy_pct"])
        student_gaps.append({
            "student_id": student_id,
            "overall_accuracy_pct": overall_pct,
            "weak_topics": weak_topics[:5],
            "strong_topics": strong_topics[:5],
            "total_questions": s["total"],
        })
    student_gaps.sort(key=lambda x: x["overall_accuracy_pct"])

    # Class overview
    total_students = len(student_stats)
    exams = answers.values("attempt__exam_id").distinct().count()
    avg_score = round(
        sum(s["correct"] for s in student_stats.values()) /
        max(sum(s["total"] for s in student_stats.values()), 1) * 100, 1
    )

    return {
        "topic_summary": topic_summary,
        "student_gaps": student_gaps,
        "class_overview": {
            "total_students": total_students,
            "total_exams": exams,
            "avg_score_pct": avg_score,
        },
    }


def generate_ai_progress_insights(progress_data):
    """Use AI to generate natural-language insights from progress analysis data.
    Returns a list of insight strings.
    """
    if not settings.ANTHROPIC_API_KEY or anthropic is None:
        return _offline_progress_insights(progress_data)

    topic_summary = progress_data.get("topic_summary", [])
    student_gaps = progress_data.get("student_gaps", [])
    overview = progress_data.get("class_overview", {})

    prompt = f"""You are an AI academic advisor analyzing student performance data.

Class overview: {overview['total_students']} students, {overview['total_exams']} exams, average accuracy {overview['avg_score_pct']}%

Topic breakdown (sorted by weakest first):
{json.dumps(topic_summary[:10], indent=2)}

Weakest students (first 5):
{json.dumps(student_gaps[:5], indent=2)}

Provide 3-5 concise, actionable insights for the teacher. Focus on:
1. Which topics the class struggles with most
2. Which students need intervention
3. Suggested teaching strategies for weak areas

Return as a JSON array of strings, no commentary:
["insight 1", "insight 2", ...]"""

    try:
        raw = _timed_anthropic_call(prompt, "progress_analysis")
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(i) for i in data[:5]]
    except Exception as exc:
        _log_usage(
            feature="progress_analysis",
            status="error",
            error_message=str(exc)[:500],
        )
    return _offline_progress_insights(progress_data)


def _offline_progress_insights(progress_data):
    """Deterministic insights without AI — works offline."""
    insights = []
    overview = progress_data.get("class_overview", {})
    topics = progress_data.get("topic_summary", [])
    gaps = progress_data.get("student_gaps", [])

    if overview.get("total_students", 0) == 0:
        return ["No exam data available yet. Insights will appear after students complete exams."]

    avg = overview.get("avg_score_pct", 0)
    if avg < 40:
        insights.append(f"⚠️ The class average accuracy is low ({avg}%). Consider reviewing foundational concepts before moving forward.")
    elif avg >= 70:
        insights.append(f"✅ The class is performing well overall ({avg}% average accuracy).")
    else:
        insights.append(f"📊 The class average accuracy is {avg}%. There's room for improvement in several areas.")

    if topics:
        weak = [t for t in topics if t["accuracy_pct"] < 50]
        if weak:
            names = ", ".join(t["topic"] for t in weak[:3])
            insights.append(f"🔴 Topics needing attention: {names}. Consider dedicating extra class time or practice materials to these areas.")

    if gaps and gaps[0]["overall_accuracy_pct"] < 40:
        insights.append(f"👨‍🎓 {len([g for g in gaps if g['overall_accuracy_pct'] < 40])} student(s) are scoring below 40% accuracy — they may need one-on-one support.")

    if not insights:
        insights.append("📊 Performance looks balanced across topics and students.")

    return insights


def _extract_topic(question_text):
    """Extract a short topic label from a question's text.
    Uses simple keyword extraction for the offline path.
    """
    text = question_text.strip()
    # Try to find a noun phrase before common question patterns
    for pattern in [r'^(?:What|How|Which|Explain|Describe|Discuss|Compare)\s+(?:is|are|does|do)?\s*(?:the\s+)?(.+?)\s*[?]',
                    r'^"?(.+?)"?\s*(?:is|are)\s+(?:a|an|the|defined|meant)']:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            topic = m.group(1).strip()[:60]
            if len(topic) > 5:
                return topic
    # Fallback: first few significant words
    words = re.findall(r'[A-Za-z]{3,}', text)
    stop = {'the', 'this', 'that', 'with', 'from', 'what', 'which', 'when', 'where',
            'how', 'why', 'does', 'explain', 'describe', 'compare', 'following'}
    meaningful = [w for w in words if w.lower() not in stop][:3]
    return ' '.join(meaningful) if meaningful else text[:40]


# ---------------------------------------------------------------------------
# Public API — CQ Answer Evaluation
# ---------------------------------------------------------------------------
def evaluate_cq_answer(answer_data, reference_answer, question_text):
    """Use AI to evaluate a CQ answer against the reference.

    Returns a dict with:
      - suggested_score: 0-100 normalized score
      - feedback: brief teacher-facing feedback
      - strengths: list of strong points
      - gaps: list of missing elements

    The teacher MUST review and confirm/adjust before saving — human-in-the-loop.
    """
    if not answer_data or not reference_answer:
        return {
            "suggested_score": 0,
            "feedback": "No answer provided or no reference available.",
            "strengths": [],
            "gaps": ["Answer is missing."],
        }

    # Normalize to strings
    answer_text = str(answer_data).strip()
    ref_text = str(reference_answer).strip()

    if not settings.ANTHROPIC_API_KEY or anthropic is None:
        return _offline_cq_evaluation(answer_text, ref_text)

    prompt = f"""You are an expert university grader evaluating a student's answer.

QUESTION: {question_text[:500]}

REFERENCE ANSWER: {ref_text[:1000]}

STUDENT ANSWER: {answer_text[:1000]}

Evaluate the student's answer. Return STRICT JSON — no markdown, no commentary:
{{
  "suggested_score": <0-100 integer>,
  "feedback": "brief constructive feedback for the student",
  "strengths": ["what the student did well"],
  "gaps": ["what's missing or incorrect"]
}}

Scoring guide:
- 90-100: Comprehensive, accurate, well-structured
- 70-89: Good understanding with minor gaps
- 50-69: Partial understanding, significant gaps
- 30-49: Major gaps, some relevant points
- 0-29: Mostly incorrect or irrelevant"""

    try:
        raw = _timed_anthropic_call(prompt, "cq_evaluation")
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return {
            "suggested_score": max(0, min(100, int(data.get("suggested_score", 0)))),
            "feedback": str(data.get("feedback", ""))[:500],
            "strengths": [str(s) for s in data.get("strengths", [])[:5]],
            "gaps": [str(g) for g in data.get("gaps", [])[:5]],
        }
    except Exception as exc:
        _log_usage(
            feature="cq_evaluation",
            status="error",
            error_message=str(exc)[:500],
        )
        return _offline_cq_evaluation(answer_text, ref_text)


def _offline_cq_evaluation(answer_text, reference_text):
    """Simple keyword-overlap evaluation without AI — works offline."""
    answer_words = set(re.findall(r'[a-zA-Z]{3,}', answer_text.lower()))
    ref_words = set(re.findall(r'[a-zA-Z]{3,}', reference_text.lower()))
    stop = {'the', 'this', 'that', 'with', 'from', 'into', 'have', 'been', 'they',
            'their', 'which', 'when', 'where', 'what', 'will', 'would', 'should',
            'could', 'there', 'these', 'those', 'than', 'then', 'also', 'such'}
    answer_words -= stop
    ref_words -= stop

    if not ref_words:
        return {
            "suggested_score": 50,
            "feedback": "Unable to evaluate — no reference keywords available.",
            "strengths": [],
            "gaps": [],
        }

    overlap = answer_words & ref_words
    coverage = len(overlap) / len(ref_words) if ref_words else 0
    score = min(100, int(coverage * 100))

    strengths = []
    gaps = []
    if coverage > 0.5:
        strengths.append(f"Good coverage of key concepts ({len(overlap)} key terms matched).")
    if coverage < 0.3:
        gaps.append("Missing several key concepts from the reference answer.")
    missing = ref_words - answer_words
    if missing:
        gaps.append(f"Could include terms like: {', '.join(list(missing)[:5])}.")

    feedback = f"Keyword overlap score: {score}%. "
    if score >= 70:
        feedback += "Good response covering most key concepts."
    elif score >= 40:
        feedback += "Partial coverage — consider adding more relevant details."
    else:
        feedback += "Significant gaps — review the material and try again."

    return {
        "suggested_score": score,
        "feedback": feedback,
        "strengths": strengths,
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# Public API — Teacher Student Overview
# ---------------------------------------------------------------------------
def generate_teacher_student_overview(course_offering):
    """Generate an aggregated view of all students' performance for a teacher.

    Returns a list of student summaries with:
      - student: user object
      - accuracy_pct: overall accuracy
      - weak_topics: list of weak topics
      - strong_topics: list of strong topics
      - exams_taken: number of exams completed
      - risk_level: 'high', 'medium', or 'low'

    This is a read-only aggregation — no AI API calls needed.
    """
    from accounts.models import User
    from exams.models import ExamAnswer

    students = User.objects.filter(
        role="student",
        enrollments__course_offering=course_offering,
    ).distinct()

    student_summaries = []
    for student in students:
        # Get all answers for this student
        answers = ExamAnswer.objects.filter(
            attempt__exam__course_offering=course_offering,
            attempt__student=student,
            submitted_at__isnull=False,
        ).select_related(
            "exam_question", "exam_question__question"
        )

        if not answers:
            student_summaries.append({
                "student": student,
                "accuracy_pct": 0,
                "weak_topics": [],
                "strong_topics": [],
                "exams_taken": 0,
                "risk_level": "no_data",
                "total_questions": 0,
            })
            continue

        # Analyze per-topic performance
        topic_stats = defaultdict(lambda: {
            "total": 0, "correct": 0, "earned": 0, "possible": 0
        })
        total_correct = 0
        total_questions = 0
        exams_taken = answers.values("attempt__exam_id").distinct().count()

        for ans in answers:
            q = ans.exam_question.question
            eq = ans.exam_question
            topic = _extract_topic(q.text)
            score = ans.auto_score or 0
            is_correct = (
                score > 0 if q.type == "mcq"
                else (ans.manual_score is not None and ans.manual_score > 0)
            )
            marks_earned = score if q.type == "mcq" else (ans.manual_score or 0)
            marks_possible = eq.marks

            topic_stats[topic]["total"] += 1
            if is_correct:
                topic_stats[topic]["correct"] += 1
                total_correct += 1
            total_questions += 1
            topic_stats[topic]["earned"] += marks_earned
            topic_stats[topic]["possible"] += marks_possible

        # Classify topics
        weak_topics = []
        strong_topics = []
        for topic, stats in topic_stats.items():
            pct = round(100 * stats["correct"] / stats["total"], 1) if stats["total"] else 0
            topic_info = {
                "topic": topic,
                "accuracy_pct": pct,
                "questions_attempted": stats["total"],
                "correct": stats["correct"],
            }
            if pct < 50:
                weak_topics.append(topic_info)
            elif pct >= 80:
                strong_topics.append(topic_info)

        weak_topics.sort(key=lambda x: x["accuracy_pct"])
        strong_topics.sort(key=lambda x: -x["accuracy_pct"])

        overall_accuracy = round(100 * total_correct / total_questions, 1) if total_questions else 0

        # Determine risk level
        if overall_accuracy < 40:
            risk_level = "high"
        elif overall_accuracy < 60:
            risk_level = "medium"
        else:
            risk_level = "low"

        student_summaries.append({
            "student": student,
            "accuracy_pct": overall_accuracy,
            "weak_topics": weak_topics[:5],
            "strong_topics": strong_topics[:3],
            "exams_taken": exams_taken,
            "risk_level": risk_level,
            "total_questions": total_questions,
        })

    # Sort by risk (high first), then by accuracy (lowest first)
    risk_order = {"high": 0, "medium": 1, "low": 2, "no_data": 3}
    student_summaries.sort(key=lambda x: (risk_order.get(x["risk_level"], 3), x["accuracy_pct"]))

    return student_summaries


# ---------------------------------------------------------------------------
# Public API — Student Study Recommendations
# ---------------------------------------------------------------------------
def generate_student_recommendations(student, course_offering):
    """Generate personalized study recommendations for a student in a course.

    Analyzes the student's exam performance and produces:
      - weak_topics: topics needing improvement with accuracy data
      - strong_topics: topics where the student excels
      - recommendations: actionable study suggestions
      - overall_stats: performance summary

    The AI generates natural-language recommendations; the offline path
    provides rule-based suggestions.
    """
    from exams.models import ExamAnswer

    # Get all answers for this student in this offering
    answers = ExamAnswer.objects.filter(
        attempt__exam__course_offering=course_offering,
        attempt__student=student,
        submitted_at__isnull=False,
    ).select_related(
        "exam_question", "exam_question__question"
    )

    if not answers:
        return {
            "weak_topics": [],
            "strong_topics": [],
            "recommendations": [
                "You haven't taken any exams in this course yet. Start by reviewing the course materials and taking a practice exam when available."
            ],
            "overall_stats": {
                "total_questions": 0,
                "correct_answers": 0,
                "accuracy_pct": 0,
                "exams_taken": 0,
            },
        }

    # Analyze per-topic performance
    topic_stats = defaultdict(lambda: {
        "total": 0, "correct": 0, "earned": 0, "possible": 0
    })
    total_correct = 0
    total_questions = 0
    exams_taken = answers.values("attempt__exam_id").distinct().count()

    for ans in answers:
        q = ans.exam_question.question
        eq = ans.exam_question
        topic = _extract_topic(q.text)
        score = ans.auto_score or 0
        is_correct = score > 0 if q.type == "mcq" else (ans.manual_score is not None and ans.manual_score > 0)
        marks_earned = score if q.type == "mcq" else (ans.manual_score or 0)
        marks_possible = eq.marks

        topic_stats[topic]["total"] += 1
        if is_correct:
            topic_stats[topic]["correct"] += 1
            total_correct += 1
        total_questions += 1
        topic_stats[topic]["earned"] += marks_earned
        topic_stats[topic]["possible"] += marks_possible

    # Classify topics
    weak_topics = []
    strong_topics = []
    for topic, stats in topic_stats.items():
        pct = round(100 * stats["correct"] / stats["total"], 1) if stats["total"] else 0
        topic_info = {
            "topic": topic,
            "accuracy_pct": pct,
            "questions_attempted": stats["total"],
            "correct": stats["correct"],
            "marks_earned": stats["earned"],
            "marks_possible": stats["possible"],
        }
        if pct < 50:
            weak_topics.append(topic_info)
        elif pct >= 80:
            strong_topics.append(topic_info)

    weak_topics.sort(key=lambda x: x["accuracy_pct"])
    strong_topics.sort(key=lambda x: -x["accuracy_pct"])

    overall_accuracy = round(100 * total_correct / total_questions, 1) if total_questions else 0

    # Generate recommendations
    if settings.ANTHROPIC_API_KEY and anthropic is not None:
        try:
            recommendations = _generate_ai_recommendations(
                student, course_offering, weak_topics, strong_topics, overall_accuracy
            )
        except Exception as exc:
            _log_usage(
                feature="progress_analysis",
                status="error",
                error_message=str(exc)[:500],
            )
            recommendations = _offline_recommendations(weak_topics, strong_topics, overall_accuracy)
    else:
        recommendations = _offline_recommendations(weak_topics, strong_topics, overall_accuracy)
        _log_usage(feature="progress_analysis", status="fallback")

    return {
        "weak_topics": weak_topics,
        "strong_topics": strong_topics,
        "recommendations": recommendations,
        "overall_stats": {
            "total_questions": total_questions,
            "correct_answers": total_correct,
            "accuracy_pct": overall_accuracy,
            "exams_taken": exams_taken,
        },
    }


def _generate_ai_recommendations(student, course_offering, weak_topics, strong_topics, overall_accuracy):
    """Use AI to generate personalized study recommendations."""
    student_name = student.get_full_name() or student.username
    course_name = f"{course_offering.course.code} — {course_offering.course.title}"

    weak_summary = json.dumps(weak_topics[:5], indent=2) if weak_topics else "None"
    strong_summary = json.dumps(strong_topics[:3], indent=2) if strong_topics else "None"

    prompt = f"""You are a supportive AI academic advisor for a university student.

Student: {student_name}
Course: {course_name}
Overall accuracy: {overall_accuracy}%

Weak topics (need improvement):
{weak_summary}

Strong topics:
{strong_summary}

Generate 4-6 personalized, actionable study recommendations. Be specific and encouraging.
Focus on:
1. Which topics to prioritize for review
2. Specific study strategies (practice problems, concept mapping, etc.)
3. Resources to use (textbook chapters, online tutorials, study groups)
4. Time management tips for improvement

Return as a JSON array of strings, no commentary:
["recommendation 1", "recommendation 2", ...]"""

    raw = _timed_anthropic_call(prompt, "progress_analysis")
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(raw)
    if isinstance(data, list):
        return [str(r) for r in data[:6]]
    return _offline_recommendations(weak_topics, strong_topics, overall_accuracy)


def _offline_recommendations(weak_topics, strong_topics, overall_accuracy):
    """Rule-based study recommendations without AI — works offline."""
    recommendations = []

    if overall_accuracy < 40:
        recommendations.append(
            "⚠️ Your overall accuracy is below 40%. Consider scheduling a meeting with your instructor to discuss areas of difficulty."
        )
    elif overall_accuracy < 60:
        recommendations.append(
            "📊 Your accuracy is around the passing range. With focused review of weak topics, you can improve significantly."
        )
    elif overall_accuracy >= 80:
        recommendations.append(
            "✅ Great work! You're performing well. Focus on maintaining this level and helping classmates who may struggle."
        )

    if weak_topics:
        topic_names = ", ".join(t["topic"] for t in weak_topics[:3])
        recommendations.append(
            f"🔴 Priority topics to review: {topic_names}. Spend extra time on these areas before the next exam."
        )
        if weak_topics[0]["accuracy_pct"] < 30:
            recommendations.append(
                f"📚 The topic \"{weak_topics[0]['topic']}\" needs significant review. Consider re-reading the relevant lecture notes and doing practice problems."
            )
    else:
        recommendations.append(
            "✅ No weak topics identified — keep up the great work across all areas!"
        )

    if strong_topics:
        names = ", ".join(t["topic"] for t in strong_topics[:2])
        recommendations.append(
            f"💪 Your strengths: {names}. Use these as anchors when studying — connecting new concepts to what you already know helps retention."
        )

    # General study tips
    if overall_accuracy < 70:
        recommendations.append(
            "⏰ Try spaced repetition: review material in short sessions (20-30 min) over several days rather than cramming."
        )
        recommendations.append(
            "📝 Practice active recall: test yourself on concepts without looking at notes, then check your answers."
        )

    return recommendations


# ---------------------------------------------------------------------------
# Public API — Student Topic Performance Cache Refresh
# ---------------------------------------------------------------------------
def refresh_student_topic_performance(course_offering, student=None):
    """Refresh cached StudentTopicPerformance records for a course offering.

    Called automatically after exam grading and available as a management
    command for manual refresh. Updates the cache so analytics pages load
    instantly without re-analyzing raw exam data.

    Args:
        course_offering: The CourseOffering to refresh.
        student: Optional specific student. If None, refreshes all enrolled.
    """
    from accounts.models import User
    from exams.models import ExamAnswer
    from .models import StudentTopicPerformance

    students = User.objects.filter(
        role="student",
        enrollments__course_offering=course_offering,
    ).distinct()
    if student:
        students = students.filter(pk=student.pk)

    for stu in students:
        answers = ExamAnswer.objects.filter(
            attempt__exam__course_offering=course_offering,
            attempt__student=stu,
            submitted_at__isnull=False,
        ).select_related(
            "exam_question", "exam_question__question"
        )

        if not answers:
            continue

        # Aggregate by topic
        topic_data = defaultdict(lambda: {
            "total": 0, "correct": 0, "earned": Decimal(0), "possible": Decimal(0)
        })

        for ans in answers:
            q = ans.exam_question.question
            eq = ans.exam_question
            topic = _extract_topic(q.text)
            score = ans.auto_score or 0
            is_correct = (
                score > 0 if q.type == "mcq"
                else (ans.manual_score is not None and ans.manual_score > 0)
            )
            marks_earned = Decimal(str(score if q.type == "mcq" else (ans.manual_score or 0)))
            marks_possible = Decimal(str(eq.marks))

            topic_data[topic]["total"] += 1
            if is_correct:
                topic_data[topic]["correct"] += 1
            topic_data[topic]["earned"] += marks_earned
            topic_data[topic]["possible"] += marks_possible

        # Upsert StudentTopicPerformance records
        for topic, data in topic_data.items():
            total = data["total"]
            correct = data["correct"]
            pct = round(100 * correct / total, 1) if total else 0

            if pct >= 80:
                level = "strong"
            elif pct >= 50:
                level = "moderate"
            elif pct >= 25:
                level = "weak"
            else:
                level = "critical"

            StudentTopicPerformance.objects.update_or_create(
                student=stu,
                course_offering=course_offering,
                topic=topic,
                defaults={
                    "total_questions": total,
                    "correct_answers": correct,
                    "total_marks_earned": data["earned"],
                    "total_marks_possible": data["possible"],
                    "strength_level": level,
                },
            )

    # Check for weak topics and send notifications
    notified = check_and_notify_weak_topics(course_offering, student=student)

    return students.count()


# ---------------------------------------------------------------------------
# Public API — Weak Topics Email Notifications
# ---------------------------------------------------------------------------
def check_and_notify_weak_topics(course_offering, student=None):
    """Check for students with critically weak topics and send notifications.

    Called after cache refresh. Respects AI_NOTIFY_WEAK_TOPICS setting.
    Only notifies students whose accuracy on any topic falls below the
    configured threshold.

    Args:
        course_offering: The CourseOffering to check.
        student: Optional specific student to check.

    Returns:
        List of student emails that were notified.
    """
    from django.conf import settings as django_settings
    from .models import StudentTopicPerformance

    if not getattr(django_settings, "AI_NOTIFY_WEAK_TOPICS", True):
        return []

    threshold = getattr(django_settings, "AI_WEAK_TOPIC_THRESHOLD", 30)

    # Get students with critically weak topics
    qs = StudentTopicPerformance.objects.filter(
        course_offering=course_offering,
        strength_level="critical",
    ).select_related("student", "course_offering__course")

    if student:
        qs = qs.filter(student=student)

    # Group by student
    student_weak_topics = defaultdict(list)
    for perf in qs:
        if perf.accuracy_pct < threshold:
            student_weak_topics[perf.student].append(perf)

    notified = []
    for stu, topics in student_weak_topics.items():
        if stu.email:
            _send_weak_topics_email(stu, course_offering, topics)
            notified.append(stu.email)

    return notified


def _send_weak_topics_email(student, course_offering, weak_topics):
    """Send an email notification about critically weak topics."""
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.conf import settings as django_settings

    course = course_offering.course
    topic_data = [
        {
            "name": t.topic,
            "accuracy": t.accuracy_pct,
            "correct": t.correct_answers,
            "total": t.total_questions,
        }
        for t in weak_topics
    ]

    subject = f"📚 Study Alert: Weak Topics in {course.code} — {course.title}"

    # Try to use template, fall back to plain text
    try:
        html_message = render_to_string("ai/email_weak_topics.html", {
            "student": student,
            "course": course,
            "offering": course_offering,
            "weak_topics": topic_data,
            "threshold": getattr(django_settings, "AI_WEAK_TOPIC_THRESHOLD", 30),
        })
        plain_message = render_to_string("ai/email_weak_topics.txt", {
            "student": student,
            "course": course,
            "offering": course_offering,
            "weak_topics": topic_data,
        })
    except Exception:
        # Fallback plain text if templates not found
        topic_lines = "\n".join(
            f"  • {t['name']}: {t['accuracy']}% accuracy ({t['correct']}/{t['total']} correct)"
            for t in topic_data
        )
        plain_message = (
            f"Hi {student.get_full_name() or student.username},\n\n"
            f"Your performance in {course.code} — {course.title} shows some areas that need attention:\n\n"
            f"{topic_lines}\n\n"
            f"We recommend reviewing the lecture materials for these topics and practicing with sample questions."
            f"\n\nBest regards,\nScholaris AI Academic Advisor"
        )
        html_message = None

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[student.email],
            html_message=html_message,
            fail_silently=True,
        )
        _log_usage(
            feature="progress_analysis",
            status="success",
            metadata={
                "notification": "weak_topics_email",
                "student_id": student.id,
                "course_id": course.id,
                "weak_topics_count": len(weak_topics),
            },
        )
    except Exception as exc:
        _log_usage(
            feature="progress_analysis",
            status="error",
            error_message=f"Email notification failed: {exc}",
            metadata={
                "notification": "weak_topics_email",
                "student_id": student.id,
            },
        )


# ---------------------------------------------------------------------------
# Public API — CSV Export
# ---------------------------------------------------------------------------
def export_student_performance_csv(course_offering):
    """Generate a CSV export of student performance data for a course offering.

    Returns a tuple of (csv_string, filename) where:
      - csv_string: the CSV content as a string
      - filename: suggested filename for download

    The CSV includes:
      - Student info (name, username, email)
      - Overall metrics (accuracy, exams taken, questions answered)
      - Risk level
      - Weak topics (comma-separated)
      - Strong topics (comma-separated)
    """
    summaries = generate_teacher_student_overview(course_offering)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "Student Name",
        "Username",
        "Email",
        "Accuracy %",
        "Exams Taken",
        "Questions Answered",
        "Risk Level",
        "Weak Topics",
        "Weak Topic Accuracies",
        "Strong Topics",
        "Strong Topic Accuracies",
    ])

    # Data rows
    for s in summaries:
        student = s["student"]
        weak_topics = s.get("weak_topics", [])
        strong_topics = s.get("strong_topics", [])

        writer.writerow([
            student.get_full_name() or student.username,
            student.username,
            student.email or "",
            s["accuracy_pct"],
            s["exams_taken"],
            s.get("total_questions", 0),
            s["risk_level"].upper(),
            "; ".join(t["topic"] for t in weak_topics),
            "; ".join(f"{t['accuracy_pct']}%" for t in weak_topics),
            "; ".join(t["topic"] for t in strong_topics),
            "; ".join(f"{t['accuracy_pct']}%" for t in strong_topics),
        ])

    # Generate filename
    course_code = course_offering.course.code
    semester = course_offering.semester.name.replace(" ", "_")
    filename = f"{course_code}_{semester}_student_performance.csv"

    return output.getvalue(), filename


def export_topic_analysis_csv(course_offering):
    """Generate a CSV export of topic-level analysis for a course offering.

    Returns a tuple of (csv_string, filename) where:
      - csv_string: the CSV content as a string
      - filename: suggested filename for download

    The CSV includes per-student, per-topic breakdown:
      - Student info
      - Topic name
      - Questions attempted, correct, accuracy
      - Marks earned, possible
      - Strength level
    """
    from accounts.models import User
    from exams.models import ExamAnswer
    from .models import StudentTopicPerformance

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "Student Name",
        "Username",
        "Topic",
        "Questions Attempted",
        "Correct Answers",
        "Accuracy %",
        "Marks Earned",
        "Marks Possible",
        "Score %",
        "Strength Level",
    ])

    # Get all topic performance records for this offering
    performances = StudentTopicPerformance.objects.filter(
        course_offering=course_offering,
    ).select_related("student").order_by("student__username", "topic")

    for perf in performances:
        writer.writerow([
            perf.student.get_full_name() or perf.student.username,
            perf.student.username,
            perf.topic,
            perf.total_questions,
            perf.correct_answers,
            perf.accuracy_pct,
            float(perf.total_marks_earned),
            float(perf.total_marks_possible),
            perf.score_pct,
            perf.strength_level.upper(),
        ])

    # Generate filename
    course_code = course_offering.course.code
    semester = course_offering.semester.name.replace(" ", "_")
    filename = f"{course_code}_{semester}_topic_analysis.csv"

    return output.getvalue(), filename
