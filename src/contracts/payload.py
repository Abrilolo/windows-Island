"""Strict Room v6 (`LauncherDatabase`) payload contracts and JSON Schema for Minimal Launcher."""

from __future__ import annotations

from enum import Enum
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FinanceKind(str, Enum):
    """Valid `finances.kind` values in Minimal Launcher (`LauncherDatabase` v6)."""

    INCOME_FIXED = "INCOME_FIXED"
    TRANSFER = "TRANSFER"
    GIFT = "GIFT"
    SERVICE = "SERVICE"
    FIXED = "FIXED"
    EXTRA = "EXTRA"
    SHARED = "SHARED"


class NoteCategory(str, Enum):
    """Valid `notes.category` values in Minimal Launcher (`LauncherDatabase` v6)."""

    GENERAL = "GENERAL"
    WORK = "WORK"
    IDEAS = "IDEAS"
    FINANCES = "FINANCES"
    DIET = "DIET"
    SCHOOL = "SCHOOL"
    EXERCISE = "EXERCISE"
    FOOD = "FOOD"


class ReminderPriority(str, Enum):
    """Priority levels for reminders."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReminderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, description="Short reminder title")
    hour: int = Field(..., ge=0, le=23, description="24-hour clock hour (0-23)")
    minute: int = Field(..., ge=0, le=59, description="Minute of the hour (0-59)")
    dueDateIso: str = Field(
        ...,
        description="ISO-8601 local date-time string, e.g. 2026-11-03T18:00:00",
    )
    priority: ReminderPriority = Field(
        default=ReminderPriority.MEDIUM,
        description="Reminder priority: low, medium, or high",
    )
    phaseId: str = Field(
        default="work",
        description="Day phase identifier, e.g. morning, work, evening, night",
    )


class FinanceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amountCents: int = Field(
        ...,
        description="Amount in integer cents (multiply currency units by 100, e.g. 120 -> 12000)",
    )
    description: str = Field(..., min_length=1, description="Concept or merchant description")
    kind: FinanceKind = Field(..., description="Transaction kind from LauncherDatabase v6")
    category: str = Field(..., min_length=1, description="Human-readable category, e.g. Comida, Servicios")
    pendingFromOthersCents: int = Field(
        default=0,
        ge=0,
        description="Amount in cents owed by other people (for SHARED expenses, otherwise 0)",
    )


class MealItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=1, description="Food item and quantity description")
    servings: float = Field(default=1.0, gt=0, description="Number of servings")
    slotId: str = Field(
        default="comida",
        description="Meal slot: desayuno, comida, cena, or snack",
    )
    kcal: float = Field(..., ge=0, description="Estimated kilocalories")
    proteinG: float = Field(..., ge=0, description="Estimated protein in grams")
    carbsG: float = Field(..., ge=0, description="Estimated carbohydrates in grams")
    fatG: float = Field(..., ge=0, description="Estimated fat in grams")
    fiberG: float = Field(default=0.0, ge=0, description="Estimated dietary fiber in grams")


class WorkoutItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise: str = Field(..., min_length=1, description="Exercise name, e.g. Press de banca")
    sets: int = Field(..., ge=1, description="Number of sets performed")
    reps: int = Field(..., ge=1, description="Repetitions per set")
    weightKg: float = Field(default=0.0, ge=0, description="Weight in kilograms (0 if bodyweight)")
    notes: str = Field(default="", description="Optional technique or RPE notes")


class NoteItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: NoteCategory = Field(..., description="Note category from LauncherDatabase v6")
    text: str = Field(..., min_length=1, description="Note content")


class LLMExtractionResult(BaseModel):
    """Schema passed to Ollama `format` parameter for Structured Outputs."""

    model_config = ConfigDict(extra="forbid")

    reminders: list[ReminderItem] = Field(default_factory=list)
    finances: list[FinanceItem] = Field(default_factory=list)
    meals: list[MealItem] = Field(default_factory=list)
    workouts: list[WorkoutItem] = Field(default_factory=list)
    notes: list[NoteItem] = Field(default_factory=list)

    def total_items(self) -> int:
        return (
            len(self.reminders)
            + len(self.finances)
            + len(self.meals)
            + len(self.workouts)
            + len(self.notes)
        )

    def is_empty(self) -> bool:
        return self.total_items() == 0

    def format_preview_lines(self) -> list[str]:
        """Generate compact human-readable lines for the Nook UI card."""
        lines: list[str] = []
        for r in self.reminders:
            lines.append(f"⏰ {r.title} ({r.hour:02d}:{r.minute:02d} · {r.priority.value})")
        for f in self.finances:
            amount_unit = f.amountCents / 100.0
            lines.append(f"💸 ${amount_unit:,.2f} — {f.description} [{f.kind.value}]")
        for m in self.meals:
            lines.append(
                f"🍽️ {m.description} ({m.kcal:.0f} kcal · {m.proteinG:.0f}g P)"
            )
        for w in self.workouts:
            lines.append(
                f"🏋️ {w.exercise}: {w.sets}x{w.reps} @ {w.weightKg:g}kg"
            )
        for n in self.notes:
            lines.append(f"📝 [{n.category.value}] {n.text}")
        return lines

    def to_ingest_payload(
        self,
        *,
        source: str = "nook-desktop",
        sent_at: int | None = None,
    ) -> IngestPayload:
        """Wrap the LLM extraction result into the full Room v6 network envelope."""
        return IngestPayload(
            source=source,
            sentAt=sent_at if sent_at is not None else int(time.time() * 1000),
            reminders=list(self.reminders),
            finances=list(self.finances),
            meals=list(self.meals),
            workouts=list(self.workouts),
            notes=list(self.notes),
        )


class IngestPayload(LLMExtractionResult):
    """Full JSON contract expected by Minimal Launcher HTTP endpoint (`/api/v1/ingest`)."""

    source: str = Field(default="nook-desktop")
    sentAt: int = Field(default_factory=lambda: int(time.time() * 1000))

    @classmethod
    def merge_all(
        cls,
        payloads: list[IngestPayload],
        *,
        source: str = "nook-desktop",
        sent_at: int | None = None,
    ) -> IngestPayload:
        """Combine multiple queued IngestPayloads into a single atomic batch."""
        merged = cls(
            source=source,
            sentAt=sent_at if sent_at is not None else int(time.time() * 1000),
        )
        for p in payloads:
            merged.reminders.extend(p.reminders)
            merged.finances.extend(p.finances)
            merged.meals.extend(p.meals)
            merged.workouts.extend(p.workouts)
            merged.notes.extend(p.notes)
        return merged

    def to_launcher_dict(self) -> dict[str, Any]:
        """Serialize to a strict JSON-compatible dict matching Minimal Launcher Room v6."""
        return self.model_dump(mode="json")
