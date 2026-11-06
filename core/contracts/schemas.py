"""Pydantic schemas for the Local Integration Engine (`backend`) and Fenn plugin layer."""

from __future__ import annotations

from enum import Enum
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContextProfile(str, Enum):
    """Active user context profile in Fenn (`IDEA.md` Section 3)."""

    WORK = "work"
    PERSONAL = "personal"
    FOCUS = "focus"


class ApprovalStatus(str, Enum):
    """Lifecycle status of an agent approval request (`IDEA.md` Fase 1)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReelAspect(str, Enum):
    """Smart Reel / Media classification aspects (`IDEA.md` D1 - Lector de reels inteligente)."""

    EXERCISE = "EXERCISE"  # Rutina / ejercicio
    BOOK = "BOOK"          # Libro / lectura
    TOOL = "TOOL"          # Herramienta nueva / software / dev
    BUY = "BUY"            # Cosas que me gustaría comprar / wishlist
    IDEA = "IDEA"          # Idea o nota general


class EngineEvent(BaseModel):
    """Normalized event emitted by an adapter or external hook (Claude Code, Codex, Git, etc.)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"evt_{int(time.time() * 1000)}")
    source: str = Field(..., description="Origin adapter or agent, e.g. claude, codex, git, media")
    kind: str = Field(..., description="Event type, e.g. session.completed, approval.requested")
    title: str = Field(..., description="Short human-readable summary")
    detail: str = Field(default="", description="Optional extended payload or path")
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    """Agent action approval request managed by AI Control Center (`IDEA.md` Fase 1)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"apr_{int(time.time() * 1000)}")
    agent: str = Field(..., description="claude, codex, or gemini")
    session_id: str = Field(default="default")
    command_or_tool: str = Field(..., description="Tool or command requesting approval")
    reason: str = Field(default="")
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))


class AgentSessionDTO(BaseModel):
    """Serializable summary of an AI agent session for the AI Control Center."""

    model_config = ConfigDict(extra="ignore")

    agent: str
    session_id: str
    title: str
    path: str
    active: bool = False
    duration_s: float | None = None
    user_turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stages: list[tuple[str, int]] = Field(default_factory=list)


class GitRepoDTO(BaseModel):
    """Local Git repository status (`IDEA.md` Fase 2 - Git Control)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    path: str
    branch: str = "main"
    dirty_files: int = 0
    ahead: int = 0
    behind: int = 0
    last_commit: str = ""
    remote_url: str = ""


class DevServiceDTO(BaseModel):
    """Local developer service / port status (`IDEA.md` Fase 2 - Dev Center)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    host: str = "127.0.0.1"
    port: int
    online: bool = False
    detail: str = ""


class WorkspaceItemDTO(BaseModel):
    """Folder or project in `C:\\Workspace` (`IDEA.md` Fase 3 - Workspace Hub)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    category: str
    path: str
    is_git_repo: bool = False
    last_modified_ms: int = 0


class DailyTaskDTO(BaseModel):
    """Task, habit, or timer item (`IDEA.md` Fase 3 - Daily Planner)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"tsk_{int(time.time() * 1000)}")
    title: str
    category: str = "WORK"  # WORK | PERSONAL | HABIT | FOCUS
    completed: bool = False
    priority: str = "medium"
    synced_to_phone: bool = False
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))


class SystemMetricsDTO(BaseModel):
    """Windows hardware & system resource metrics (`IDEA.md` Fase 4 - System Monitor)."""

    model_config = ConfigDict(extra="ignore")

    cpu_percent: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    ram_percent: float = 0.0
    disk_free_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_percent: float = 0.0
    sampled_at: int = Field(default_factory=lambda: int(time.time() * 1000))


class ReelItemDTO(BaseModel):
    """Classified reel / link / media item (`IDEA.md` D1 - Lector de reels inteligente)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"reel_{int(time.time() * 1000)}")
    raw_input: str
    aspect: ReelAspect
    title: str
    summary: str
    action_hint: str = ""
    synced_to_phone: bool = False
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))


class AutomationActionDTO(BaseModel):
    """Safe allowlisted script or automation workflow (`IDEA.md` A4 - Automation Hub)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str
    requires_confirmation: bool = False
    last_status: str = "idle"
