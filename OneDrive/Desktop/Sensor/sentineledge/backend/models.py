"""
models.py — Pydantic v2 request/response models for SentinelEdge API.

All input models include field_validator declarations that:
- Strip whitespace from string fields.
- Enforce business constraints with clear error messages.
- Return HTTP 422 automatically on failure (Pydantic handles it).

Security hardening (Change 2):
- PIN fields: min_length=4, max_length=20, alphanumeric-only pattern
- String fields: max_length enforced, min_length=1 for required fields
- Numeric fields: ge/le bounds matching real-world valid ranges
- Email fields: use EmailStr (pydantic[email]) everywhere
- PIN/password fields never returned in any Out model
"""

from __future__ import annotations

import re
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field, field_validator, model_validator, EmailStr


# ── Domain events ─────────────────────────────────────────────────────────────

class BreachEvent(BaseModel):
    parameter: str
    value: float
    threshold: float
    direction: str          # "high" | "low"
    severity: str = "WARNING"   # "WARNING" | "CRITICAL" | "EMERGENCY"


# ── API response models ───────────────────────────────────────────────────────

class ReadingOut(BaseModel):
    temperature: float
    timestamp: str
    breaches: list[BreachEvent] = Field(default_factory=list)
    is_valid: bool = True


class AlertOut(BaseModel):
    id: int
    parameter: str
    value: float
    threshold: float
    direction: str
    severity: str = "WARNING"
    timestamp: str
    acknowledged: bool
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[str] = None
    escalation_level: int
    max_escalated: bool
    cooldown_until: Optional[str] = None
    delivery_status: Optional[Dict[str, str]] = None


# ── Input models with validation ──────────────────────────────────────────────

class SubscriberIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=1, max_length=20)
    email: EmailStr = Field(max_length=254)
    escalation_order: int = Field(ge=1, le=100)
    pin: Optional[str] = None  # if provided: 4-20 alphanumeric chars, stored as bcrypt hash
    # Profile fields
    employee_id: Optional[str] = Field(default=None, max_length=50)
    department: Optional[str] = Field(default=None, max_length=100)
    designation: Optional[str] = Field(default=None, max_length=100)
    shift_timing: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=255)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v) < 2:
            raise ValueError("name must be at least 2 characters")
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def strip_phone(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not re.match(r"^\+?[0-9]{10,15}$", v):
            raise ValueError(
                "phone must be 10-15 digits, optionally prefixed with +"
            )
        return v

    @field_validator("pin", mode="before")
    @classmethod
    def strip_pin(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) < 4 or len(v) > 20:
            raise ValueError("pin must be 4-20 characters")
        if not re.match(r"^[a-zA-Z0-9]+$", v):
            raise ValueError("pin must be alphanumeric only (letters and digits)")
        return v


class SubscriberOut(BaseModel):
    id: int
    name: str
    phone: str
    email: str
    escalation_order: int
    active: bool
    has_pin: bool
    created_at: str
    # Profile fields — None if not yet populated
    employee_id: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    shift_timing: Optional[str] = None
    address: Optional[str] = None
    # NOTE: 'pin' field intentionally excluded — never returned to clients


class SubscriberUpdate(BaseModel):
    """PATCH/PUT schema — all fields optional; only supplied fields are updated."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    phone: Optional[str] = Field(default=None, min_length=1, max_length=20)
    email: Optional[EmailStr] = Field(default=None, max_length=254)
    escalation_order: Optional[int] = Field(default=None, ge=1, le=100)
    employee_id: Optional[str] = Field(default=None, max_length=50)
    department: Optional[str] = Field(default=None, max_length=100)
    designation: Optional[str] = Field(default=None, max_length=100)
    shift_timing: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=255)

    @field_validator("phone", mode="before")
    @classmethod
    def strip_phone(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^\+?[0-9]{10,15}$", v):
            raise ValueError(
                "phone must be 10-15 digits, optionally prefixed with +"
            )
        return v


class PushSubscriptionIn(BaseModel):
    subscription_json: str = Field(min_length=1, max_length=5000)


class ThresholdConfigIn(BaseModel):
    temp_high: float = Field(ge=-50.0, le=200.0)
    temp_low: float = Field(ge=-50.0, le=200.0)

    @field_validator("temp_high")
    @classmethod
    def validate_temp_high(cls, v: float) -> float:
        if not (-50.0 <= v <= 200.0):
            raise ValueError("temp_high must be between -50 and 200")
        return v

    @field_validator("temp_low")
    @classmethod
    def validate_temp_low(cls, v: float) -> float:
        if not (-50.0 <= v <= 200.0):
            raise ValueError("temp_low must be between -50 and 200")
        return v

    @model_validator(mode="after")
    def validate_high_gt_low(self) -> "ThresholdConfigIn":
        if self.temp_high <= self.temp_low:
            raise ValueError(
                f"temp_high ({self.temp_high}) must be greater than "
                f"temp_low ({self.temp_low})"
            )
        return self


class ThresholdConfigOut(BaseModel):
    temp_high: float
    temp_low: float


class ThresholdConfigDetailOut(BaseModel):
    """Extended threshold response with source tracking."""
    temperature: Dict[str, Any]
    source: str
    last_changed: str


class AcknowledgeIn(BaseModel):
    acknowledged_by: str = Field(min_length=1, max_length=50)

    @field_validator("acknowledged_by", mode="before")
    @classmethod
    def strip_acknowledged_by(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("acknowledged_by")
    @classmethod
    def validate_acknowledged_by(cls, v: str) -> str:
        if len(v) < 2:
            raise ValueError(
                "acknowledged_by must be at least 2 characters and cannot be empty"
            )
        return v


class DeliveryReceiptOut(BaseModel):
    """Single delivery receipt."""
    id: int
    alert_id: int
    channel: str
    subscriber_id: int
    escalation_level: int
    sent_at: str
    success: bool
    error_message: Optional[str] = None


class ConfigChangeOut(BaseModel):
    """Config audit log entry."""
    id: int
    changed_by: str
    field_name: str
    old_value: str
    new_value: str
    changed_at: str


# ── Auth models ───────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    """Mobile app login request: name + numeric PIN."""
    name: str = Field(min_length=1, max_length=50)
    pin: str = Field(min_length=4, max_length=20)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v) < 2:
            raise ValueError("name must be at least 2 characters")
        return v

    @field_validator("pin", mode="before")
    @classmethod
    def strip_pin(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9]+$", v):
            raise ValueError("pin must be alphanumeric only (letters and digits)")
        return v


class LoginOut(BaseModel):
    """Successful login response."""
    token: str
    subscriber_id: int
    name: str
    escalation_order: int
    message: str = "Login successful"
    # NOTE: pin intentionally excluded from all Out models


class SetPinIn(BaseModel):
    """Admin request to set or update a subscriber's PIN."""
    subscriber_id: int
    pin: str = Field(min_length=4, max_length=20)

    @field_validator("pin", mode="before")
    @classmethod
    def strip_pin(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9]+$", v):
            raise ValueError("pin must be alphanumeric only (letters and digits)")
        return v


# ── Multi-tenancy models ───────────────────────────────────────────────────────

class CompanyIn(BaseModel):
    """Request body for creating a new company."""
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100)

    @field_validator("name", "slug", mode="before")
    @classmethod
    def strip_fields(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        import re as _re
        if not _re.match(r"^[a-z0-9\-]+$", v):
            raise ValueError("slug must be lowercase letters, numbers, and hyphens only")
        return v


class CompanyOut(BaseModel):
    """Company record returned by the API."""
    id: int
    name: str
    slug: str
    is_active: bool
    created_at: str
    admin_count: int = 0
    subscriber_count: int = 0


class AssignAdminIn(BaseModel):
    """Body for POST /super-admin/companies/{id}/assign-admin."""
    admin_id: int


# ── Push token models ──────────────────────────────────────────────────────────

class PushTokenIn(BaseModel):
    """Request body for registering a push token on behalf of the current subscriber."""
    token: str = Field(min_length=1, max_length=512)
    type: str = Field(default="expo")   # "expo" | "fcm"

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("expo", "fcm"):
            raise ValueError("type must be 'expo' or 'fcm'")
        return v
