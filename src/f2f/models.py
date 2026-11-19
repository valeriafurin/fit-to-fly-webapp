from __future__ import annotations

import secrets
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

IE_LEVELS = ("IE1", "IE2", "Senior IE")
PANEL_ROLES = ("CTO", "Developer", "PM", "Observer")
OUTCOMES = ("Pass", "Needs Development")

# Priority replaces the old "weight". It is still the multiplier in the score, so pass marks are unchanged.
PRIORITY_LABELS = {1: "Low", 2: "Medium", 3: "High"}

# Page 1 feedback blocks: (key, heading). Strengths and development areas are written per block.
FEEDBACK_BLOCKS = (
    ("technical", "Technical Accuracy"),
    ("discovery", "Discovery & Curiosity"),
    ("communication", "Communication / Stakeholder Management"),
)
_SECTION_BLOCK = {"Meeting Management": "discovery", "Personal Skills": "communication"}


def feedback_block(section: str) -> str:
    """Feedback block a rubric section belongs to; pillar and custom sections count as technical."""
    return _SECTION_BLOCK.get(section, "technical")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_id() -> str:
    return secrets.token_hex(8)


class Question(BaseModel):
    id: str
    section: str
    text: str
    priority: int = Field(default=2, ge=0)
    tag: str = "All"
    desc1: str = ""
    desc3: str = ""
    desc5: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_weight(cls, data: object) -> object:
        # templates.json files saved before "priority" existed use "weight" with the same meaning.
        if isinstance(data, dict) and "priority" not in data and "weight" in data:
            data = {**data, "priority": data["weight"]}
            data.pop("weight")
        return data

    @property
    def priority_label(self) -> str:
        return PRIORITY_LABELS.get(self.priority, str(self.priority))

    def description_for(self, score: int) -> str:
        """Rubric text for a score; 2 and 4 borrow the nearest lower anchor."""
        if score >= 5:
            return self.desc5 or self.desc3
        if score >= 3:
            return self.desc3
        return self.desc1


class PillarTemplate(BaseModel):
    key: str
    scenario: str
    questions: list[Question]
    thresholds: dict[str, int]

    @property
    def max_score(self) -> int:
        return sum(q.priority * 5 for q in self.questions)

    def sections(self) -> list[tuple[str, list[Question]]]:
        out: list[tuple[str, list[Question]]] = []
        for q in self.questions:
            if not out or out[-1][0] != q.section:
                out.append((q.section, []))
            out[-1][1].append(q)
        return out


class FeedbackBlock(BaseModel):
    strengths: str = ""
    development: str = ""


class Page1(BaseModel):
    """Write-up. The summary is an executive summary of the notes, never the score."""

    overall_evaluation: str = ""
    outcome: str = ""
    summary: str = ""
    technical: FeedbackBlock = Field(default_factory=FeedbackBlock)
    discovery: FeedbackBlock = Field(default_factory=FeedbackBlock)
    communication: FeedbackBlock = Field(default_factory=FeedbackBlock)


class Assessment(BaseModel):
    scores: dict[str, int] = Field(default_factory=dict)
    notes: dict[str, str] = Field(default_factory=dict)
    page1: Page1 = Field(default_factory=Page1)
    submitted_at: datetime | None = None

    @property
    def submitted(self) -> bool:
        return self.submitted_at is not None


class PanelStatus(StrEnum):
    invited = "invited"
    opened = "opened"
    submitted = "submitted"


class Panelist(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    email: str
    role: str = "Observer"
    token: str = Field(default_factory=new_token)
    status: PanelStatus = PanelStatus.invited
    assessment: Assessment = Field(default_factory=Assessment)
    pdf: bytes | None = None


class F2FStatus(StrEnum):
    draft = "Draft"
    invited = "Invited"
    in_progress = "In progress"
    collating = "Collating"
    sent = "Sent"


class Attachment(BaseModel):
    filename: str
    content: bytes
    mime_type: str = "application/octet-stream"


class Collation(BaseModel):
    overrides: dict[str, float] = Field(default_factory=dict)
    page1: Page1 = Field(default_factory=Page1)
    pdf: bytes | None = None


class F2F(BaseModel):
    id: str = Field(default_factory=new_id)
    status: F2FStatus = F2FStatus.draft
    created_at: datetime = Field(default_factory=utcnow)
    template: PillarTemplate
    ie_level: str
    candidate_name: str
    candidate_email: str
    date: str
    start_time: str
    duration_minutes: int = 60
    time_zone: str = "Europe/Amsterdam"
    zoom_link: str = ""
    tl_name: str
    tl_email: str
    panelists: list[Panelist] = Field(default_factory=list)
    placeholders: dict[str, str] = Field(default_factory=dict)
    rollout_plan: Attachment | None = None
    collation: Collation = Field(default_factory=Collation)

    @property
    def pillar(self) -> str:
        return self.template.key

    @property
    def threshold(self) -> int:
        return self.template.thresholds[self.ie_level]

    def panelist_by_token(self, token: str) -> Panelist | None:
        for p in self.panelists:
            if secrets.compare_digest(p.token, token):
                return p
        return None

    def panelist(self, panelist_id: str) -> Panelist | None:
        return next((p for p in self.panelists if p.id == panelist_id), None)
