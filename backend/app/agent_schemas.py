from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["bug", "balance", "experience", "unknown"]
Owner = Literal["engineering", "game_design", "operations", "manual_review"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeedbackCreate(StrictModel):
    text: str = Field(min_length=3, max_length=4000)
    version: str = Field(default="2.4", min_length=1, max_length=80)


class RunCreate(StrictModel):
    feedback_id: str
    mode: Literal["mock", "openai"] = "mock"


class SearchNotes(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=80)


class SearchFeedback(StrictModel):
    query: str = Field(min_length=1, max_length=500)


class DraftTicket(StrictModel):
    title: str = Field(min_length=3, max_length=150)
    category: Category
    owner: Owner
    summary: str = Field(min_length=3, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class AgentResult(StrictModel):
    category: Category
    owner: Owner
    summary: str = Field(min_length=3, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    next_action: Literal["confirm_ticket", "needs_information"]
