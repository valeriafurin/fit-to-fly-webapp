from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from f2f.genai import GenAIClient, GenAIError
from f2f.models import (
    F2F,
    FEEDBACK_BLOCKS,
    Assessment,
    FeedbackBlock,
    Page1,
    Question,
    feedback_block,
)
from f2f.scoring import ScoreResult, rating_for

SYSTEM_PROMPT = (
    "You help Adyen team leads and panelists write fair, specific, professional feedback for a "
    "Fit-to-Fly (F2F) assessment of a new Implementation Manager. Write in clear British English, "
    "address the candidate in the third person, stay factual, and use only the evidence provided. "
    "Do not invent events that are not in the notes."
)


@dataclass
class QuestionFeedback:
    """What one question's notes say, split into strengths and development areas."""

    strengths: list[str] = field(default_factory=list)
    developments: list[str] = field(default_factory=list)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


def as_sentence(text: str) -> str:
    """Minimal tidy-up without AI: capital first letter and a full stop. AI does the real rewriting."""
    text = _flat(text)
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def score_based_feedback(rating: int | None, note: str) -> QuestionFeedback:
    """No-AI classification: the whole note counts as a strength at 3+ (meets expectations), else a development area."""
    text = _flat(note)
    if not text or rating is None:
        return QuestionFeedback()
    return QuestionFeedback([text]) if rating >= 3 else QuestionFeedback([], [as_sentence(text)])


def apply_scoring(rating: int | None, fb: QuestionFeedback, note: str) -> QuestionFeedback:
    """Keep the AI's reading consistent with the score: 4-5 must hold a strength, 1-2 a development area."""
    if rating is None:
        return fb
    if (rating >= 4 and not fb.strengths) or (rating <= 2 and not fb.developments):
        return score_based_feedback(rating, note)
    return fb


def build_page1(f2f: F2F, feedback: dict[str, QuestionFeedback], summary: str, outcome: str) -> Page1:
    """Group per-question feedback into the three feedback blocks."""
    grouped: dict[str, QuestionFeedback] = {key: QuestionFeedback() for key, _ in FEEDBACK_BLOCKS}
    for q in f2f.template.questions:
        fb = feedback.get(q.id)
        if fb is None:
            continue
        g = grouped[feedback_block(q.section)]
        g.strengths += fb.strengths
        g.developments += fb.developments

    def block(key: str) -> FeedbackBlock:
        return FeedbackBlock(
            strengths=_bullets(grouped[key].strengths), development=_bullets(grouped[key].developments)
        )

    return Page1(
        overall_evaluation=outcome,
        outcome=outcome,
        summary=summary,
        technical=block("technical"),
        discovery=block("discovery"),
        communication=block("communication"),
    )


def fallback_summary(f2f: F2F, feedback: dict[str, QuestionFeedback]) -> str:
    """Score-free summary used when AI is unavailable."""
    page = build_page1(f2f, feedback, "", "")
    labels = dict(FEEDBACK_BLOCKS)
    strong = [labels[k] for k, _ in FEEDBACK_BLOCKS if getattr(page, k).strengths]
    weak = [labels[k] for k, _ in FEEDBACK_BLOCKS if getattr(page, k).development]
    if not strong and not weak:
        return f"No notes were recorded for {f2f.candidate_name}."
    parts = [f"Summary of the notes on {f2f.candidate_name} ({f2f.pillar}, {f2f.ie_level})."]
    if strong:
        parts.append("Strengths were noted in " + ", ".join(strong) + ".")
    if weak:
        parts.append("Development areas were noted in " + ", ".join(weak) + ".")
    return " ".join(parts)


NOTES_SCHEMA = '{"summary": str, "questions": {"<question id>": {"strengths": [str], "developments": [str]}}}'


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [_flat(str(x)) for x in value if _flat(str(x))]


def _evidence(q: Question, assessment: Assessment) -> dict[str, Any]:
    return {
        "id": q.id,
        "section": q.section,
        "question": q.text,
        "score": assessment.scores.get(q.id),
        "rubric_1_needs_development": q.desc1,
        "rubric_3_meets": q.desc3,
        "rubric_5_exceeds": q.desc5,
        "notes": assessment.notes.get(q.id, "").strip(),
    }


async def analyse_notes(
    ai: GenAIClient, f2f: F2F, assessment: Assessment
) -> tuple[str, dict[str, QuestionFeedback]]:
    """Summarise the notes and classify what they say as strengths or development areas.

    Only notes are used. The score and rubric are the yardstick for the classification and are
    never repeated in the summary.
    """
    feedback = {
        q.id: score_based_feedback(assessment.scores.get(q.id), assessment.notes.get(q.id, ""))
        for q in f2f.template.questions
    }
    summary = fallback_summary(f2f, feedback)
    questions = [q for q in f2f.template.questions if assessment.notes.get(q.id, "").strip()]
    if not ai.available or not questions:
        return summary, feedback
    user = (
        f"Candidate: {f2f.candidate_name}, level {f2f.ie_level}, pillar {f2f.pillar}.\n"
        f"Panelist notes per question, with the score and rubric as the yardstick:\n"
        f"{json.dumps([_evidence(q, assessment) for q in questions], ensure_ascii=False)}\n\n"
        "Task 1 - summary: write an executive summary of 3-5 sentences of what the notes say about how "
        "the candidate performed. Do NOT mention scores, totals, ratings or pass marks.\n"
        "Task 2 - per question, decide from the notes whether each observation is a strength or a "
        "development area, judged against the rubric and the score: observations on questions scored "
        "4-5 are normally strengths, on questions scored 1-2 normally development areas, and for a 3 "
        "judge by what the note says. Rewrite each strength as one concise, standalone bullet. "
        "Write each development area as one or two complete sentences in the third person, with a subject "
        "and a verb, that say what the candidate should do differently; expand terse notes into full "
        "sentences (e.g. 'pricing unclear' -> '[Name] did not explain the pricing model clearly and should "
        "walk the merchant through the fees step by step.') without adding facts that are not in the notes. "
        "Skip anything that is not an observation. Use the question ids as keys. "
        f"Schema: {NOTES_SCHEMA}"
    )
    try:
        data = await ai.chat_json(SYSTEM_PROMPT, user)
    except GenAIError:
        return summary, feedback
    raw = data.get("questions")
    if isinstance(raw, dict):
        for q in questions:
            item = raw.get(q.id)
            if not isinstance(item, dict):
                continue
            fb = QuestionFeedback(_str_list(item.get("strengths")), _str_list(item.get("developments")))
            if fb.strengths or fb.developments:
                feedback[q.id] = apply_scoring(
                    assessment.scores.get(q.id), fb, assessment.notes.get(q.id, "")
                )
    ai_summary = _flat(str(data.get("summary") or ""))
    return ai_summary or summary, feedback


async def draft_page1(ai: GenAIClient, f2f: F2F, assessment: Assessment, result: ScoreResult) -> Page1:
    summary, feedback = await analyse_notes(ai, f2f, assessment)
    return build_page1(f2f, feedback, summary, rating_for(result.total, result.threshold))


# ---------- collation (TL) ----------

PAGE1_SCHEMA = (
    '{"summary": str, '
    '"technical": {"strengths": [str], "development": [str]}, '
    '"discovery": {"strengths": [str], "development": [str]}, '
    '"communication": {"strengths": [str], "development": [str]}}'
)


def fallback_collated_page1(f2f: F2F, pages: list[tuple[str, Page1]], result: ScoreResult) -> Page1:
    outcome = rating_for(result.total, result.threshold)

    def merge(get: Any) -> str:
        seen: list[str] = []
        for _, p in pages:
            for line in str(get(p)).splitlines():
                if line.strip() and line.strip() not in seen:
                    seen.append(line.strip())
        return "\n".join(seen)

    def block(key: str) -> FeedbackBlock:
        return FeedbackBlock(
            strengths=merge(lambda p: getattr(p, key).strengths),
            development=merge(lambda p: getattr(p, key).development),
        )

    summary = "\n\n".join(p.summary.strip() for _, p in pages if p.summary.strip())
    return Page1(
        overall_evaluation=outcome,
        outcome=outcome,
        summary=summary,
        technical=block("technical"),
        discovery=block("discovery"),
        communication=block("communication"),
    )


def _block_from_json(data: Any, fallback: FeedbackBlock) -> FeedbackBlock:
    if not isinstance(data, dict):
        return fallback
    strengths, development = _str_list(data.get("strengths")), _str_list(data.get("development"))
    return FeedbackBlock(
        strengths=_bullets(strengths) if strengths else fallback.strengths,
        development=_bullets(development) if development else fallback.development,
    )


async def draft_collated_page1(
    ai: GenAIClient, f2f: F2F, pages: list[tuple[str, Page1]], result: ScoreResult
) -> Page1:
    fallback = fallback_collated_page1(f2f, pages, result)
    if not ai.available or not pages:
        return fallback
    panel = [
        {"summary": p.summary, **{key: getattr(p, key).model_dump() for key, _ in FEEDBACK_BLOCKS}}
        for _, p in pages
    ]
    user = (
        f"Candidate: {f2f.candidate_name}, level {f2f.ie_level}, pillar {f2f.pillar}, F2F date {f2f.date}.\n"
        f"Panelist write-ups:\n{json.dumps(panel, ensure_ascii=False)}\n\n"
        "Merge the write-ups into one consolidated page. Summary: 3-5 sentence executive summary of the "
        "notes, with no scores. Per feedback block keep the strengths and development points, remove "
        "duplicates, keep points several panelists agree on and the strongest specific evidence. Write every "
        "development point as a complete sentence in the third person. Do not attribute points to "
        "individual panelists. "
        f"Schema: {PAGE1_SCHEMA}"
    )
    try:
        data = await ai.chat_json(SYSTEM_PROMPT, user)
    except GenAIError:
        return fallback
    return Page1(
        overall_evaluation=fallback.outcome,
        outcome=fallback.outcome,
        summary=_flat(str(data.get("summary") or "")) or fallback.summary,
        technical=_block_from_json(data.get("technical"), fallback.technical),
        discovery=_block_from_json(data.get("discovery"), fallback.discovery),
        communication=_block_from_json(data.get("communication"), fallback.communication),
    )
