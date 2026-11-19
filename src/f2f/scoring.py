from __future__ import annotations

from dataclasses import dataclass

from f2f.models import F2F, Assessment, PillarTemplate


@dataclass(frozen=True)
class ScoreResult:
    total: float
    max_score: int
    threshold: int
    rating: str
    answered: int
    question_count: int

    @property
    def complete(self) -> bool:
        return self.answered == self.question_count


def rating_for(total: float, threshold: int) -> str:
    return "Pass" if total >= threshold else "Needs Development"


def score(template: PillarTemplate, ratings: dict[str, float], ie_level: str) -> ScoreResult:
    total = 0.0
    answered = 0
    for q in template.questions:
        r = ratings.get(q.id)
        if r is None:
            continue
        answered += 1
        total += q.priority * r
    threshold = template.thresholds[ie_level]
    return ScoreResult(
        total=round(total, 1),
        max_score=template.max_score,
        threshold=threshold,
        rating=rating_for(round(total, 1), threshold),
        answered=answered,
        question_count=len(template.questions),
    )


def score_assessment(f2f: F2F, assessment: Assessment) -> ScoreResult:
    return score(f2f.template, {k: float(v) for k, v in assessment.scores.items()}, f2f.ie_level)


def averages(f2f: F2F) -> dict[str, float]:
    """Per-question mean across submitted panelists, rounded to one decimal."""
    out: dict[str, float] = {}
    submitted = [p.assessment for p in f2f.panelists if p.assessment.submitted]
    for q in f2f.template.questions:
        vals = [a.scores[q.id] for a in submitted if q.id in a.scores]
        if vals:
            out[q.id] = round(sum(vals) / len(vals), 1)
    return out


def collated_ratings(f2f: F2F) -> dict[str, float]:
    ratings = averages(f2f)
    ratings.update(f2f.collation.overrides)
    return ratings


def collated_score(f2f: F2F) -> ScoreResult:
    return score(f2f.template, collated_ratings(f2f), f2f.ie_level)
