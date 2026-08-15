"""
Question-generation service.

In production this is dispatched via a background worker (Celery) so the
request/response cycle is never blocked on the AI API and the API key never
reaches the client. For the hackathon build it runs synchronously behind a
thin service layer, so the exact same code path can move into a Celery task
later without touching the views.

If ANTHROPIC_API_KEY is not configured, a built-in offline generator produces
plausible draft questions from the material text (extractive), so the full
human-in-the-loop flow can still be demonstrated without any external service.
"""
import json
import random
import re

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
# Public API
# ---------------------------------------------------------------------------
def generate_questions(material):
    """Generate draft questions from a Material. Returns a list of draft dicts.

    Prefers the Anthropic API; falls back to the offline generator when no
    ANTHROPIC_API_KEY is configured or the API call fails.
    """
    # Prefer the DB-cached text (works even when the uploaded file is not
    # reachable, e.g. ephemeral disk on a serverless deploy).
    material_text = material.content_text or extract_text(material.file)
    if not material_text.strip():
        material_text = f"{material.title}. This lecture material covers the core "
        f"concepts of {material.title} for the course."

    used_ai = False
    if settings.ANTHROPIC_API_KEY and anthropic is not None:
        try:
            drafts = _generate_with_anthropic(material_text)
            used_ai = True
        except Exception:
            drafts = None
    if not used_ai:
        drafts = _generate_offline(material_text)

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
