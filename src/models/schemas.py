"""Pydantic models for data validation across the system."""

from typing import Optional

from pydantic import BaseModel, Field


class FeedbackItem(BaseModel):
    """A single piece of user feedback from any source."""

    source_id: str
    source_type: str  # 'app_store_review' | 'support_email' | 'manual_input'
    content_text: str
    subject: Optional[str] = None
    sender: Optional[str] = None
    rating: Optional[int] = None
    platform: Optional[str] = None
    priority_hint: Optional[str] = None
    original_date: Optional[str] = None
    app_version: Optional[str] = None
    source_file: Optional[str] = None
    raw_json: Optional[str] = None


class ClassificationResult(BaseModel):
    """Output of the Feedback Classifier agent."""

    category: str  # Bug | Feature Request | Praise | Complaint | Spam
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class BugAnalysis(BaseModel):
    """Output of the Bug Analyzer agent."""

    severity: str  # Critical | Major | Minor | Cosmetic
    affected_component: str
    platform_details: dict = Field(default_factory=dict)
    steps_to_reproduce: list[str] = Field(default_factory=list)
    expected_behavior: str = ""
    actual_behavior: str = ""
    suggested_title: str
    suggested_priority: str  # Critical | High | Medium | Low
    suggested_actions: list[str] = Field(default_factory=list)


class FeatureAnalysis(BaseModel):
    """Output of the Feature Extractor agent."""

    feature_name: str
    description: str
    user_impact: str  # High | Medium | Low
    demand_signal: str  # Strong | Moderate | Weak
    existing_alternatives: str = ""
    suggested_title: str
    suggested_priority: str  # High | Medium | Low
    suggested_actions: list[str] = Field(default_factory=list)


class TicketData(BaseModel):
    """A generated ticket ready for storage."""

    ticket_id: str  # TKT-YYYYMMDD-NNN
    feedback_id: int
    category: str
    confidence: float
    title: str
    description: str
    priority: str  # Critical | High | Medium | Low
    severity: Optional[str] = None
    technical_details: Optional[str] = None  # JSON string
    feature_details: Optional[str] = None  # JSON string
    suggested_actions: Optional[str] = None  # JSON array string


class QualityReview(BaseModel):
    """Output of the Quality Critic agent."""

    score: float = Field(ge=0.0, le=10.0)
    breakdown: dict = Field(default_factory=dict)
    approved: bool
    notes: str
    revision_suggestions: list[str] = Field(default_factory=list)
