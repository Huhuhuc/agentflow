from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    email: str
    name: str
    role: str


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    graph: dict[str, Any] = Field(default_factory=lambda: {"nodes": [], "edges": []})


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    graph: dict[str, Any] | None = None


class WorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    status: str
    graph: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ExecutionRequest(BaseModel):
    input_data: dict[str, Any] = Field(default_factory=dict)


class ExecutionLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    node_id: str
    node_name: str
    node_type: str
    status: str
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    duration_ms: int
    token_used: int
    error_message: str | None


class ExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workflow_id: str
    status: str
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    error_message: str | None
    duration_ms: int
    token_used: int
    cost: float
    created_at: datetime
    logs: list[ExecutionLogOut] = []

