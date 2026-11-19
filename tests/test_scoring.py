from __future__ import annotations

import json

import pytest

from f2f.models import F2F, Assessment, Panelist, PillarTemplate
from f2f.scoring import averages, collated_score, rating_for, score
from f2f.templates_repo import SEED_PATH


def pillars() -> dict[str, PillarTemplate]:
    data = json.loads(SEED_PATH.read_text())
    return {p["key"]: PillarTemplate.model_validate(p) for p in data["pillars"]}


@pytest.mark.parametrize(("key", "maximum"), [("Digital", 195), ("UC", 210), ("P&FS", 235)])
def test_seeded_max_scores(key: str, maximum: int) -> None:
    assert pillars()[key].max_score == maximum


@pytest.mark.parametrize(
    ("key", "level", "minimum"),
    [
        ("Digital", "IE1", 90),
        ("Digital", "IE2", 117),
        ("Digital", "Senior IE", 171),
        ("UC", "IE1", 99),
        ("UC", "IE2", 126),
        ("UC", "Senior IE", 192),
        ("P&FS", "IE1", 117),
        ("P&FS", "IE2", 141),
        ("P&FS", "Senior IE", 219),
    ],
)
def test_thresholds(key: str, level: str, minimum: int) -> None:
    t = pillars()[key]
    assert t.thresholds[level] == minimum
    assert rating_for(minimum, t.thresholds[level]) == "Pass"
    assert rating_for(minimum - 0.1, t.thresholds[level]) == "Needs Development"


def test_weighted_total() -> None:
    t = pillars()["Digital"]
    ratings = {q.id: 5.0 for q in t.questions}
    r = score(t, ratings, "Senior IE")
    assert r.total == 195 and r.rating == "Pass" and r.complete
    ratings = {q.id: 1.0 for q in t.questions}
    assert score(t, ratings, "IE1").total == 39


def test_partial_scoring_counts_answered() -> None:
    t = pillars()["UC"]
    q = t.questions[0]
    r = score(t, {q.id: 4.0}, "IE1")
    assert r.total == q.priority * 4 and r.answered == 1 and not r.complete


def _f2f(scores: list[dict[str, int]]) -> F2F:
    t = pillars()["Digital"]
    panel = []
    for i, s in enumerate(scores):
        a = Assessment(scores=s)
        a.submitted_at = a.submitted_at or __import__("f2f.models").models.utcnow()
        panel.append(Panelist(name=f"P{i}", email=f"p{i}@x.com", assessment=a))
    return F2F(
        template=t,
        ie_level="IE2",
        candidate_name="C",
        candidate_email="c@x.com",
        date="2026-11-10",
        start_time="10:00",
        tl_name="T",
        tl_email="t@x.com",
        panelists=panel,
    )


def test_collation_average_and_override() -> None:
    t = pillars()["Digital"]
    a = {q.id: 3 for q in t.questions}
    b = {q.id: 4 for q in t.questions}
    c = {q.id: 4 for q in t.questions}
    f = _f2f([a, b, c])
    avg = averages(f)
    assert all(v == 3.7 for v in avg.values())
    before = collated_score(f)
    assert before.total == round(sum(q.priority * 3.7 for q in t.questions), 1)
    q0 = t.questions[0]
    f.collation.overrides[q0.id] = 5.0
    after = collated_score(f)
    assert after.total == pytest.approx(before.total + q0.priority * (5.0 - 3.7), abs=0.05)


def test_collation_ignores_unsubmitted() -> None:
    t = pillars()["Digital"]
    f = _f2f([{q.id: 5 for q in t.questions}])
    f.panelists.append(
        Panelist(name="late", email="l@x.com", assessment=Assessment(scores={q.id: 1 for q in t.questions}))
    )
    assert collated_score(f).total == 195
