"""ORM models.

Data classes are separated by lifecycle (see docs/SECURITY.md, "Data classes"):
* audit records  - ``AuditLog``: append-only, never deleted by users
* user-owned     - analyses, operations, experiments, reports: deletable by their owner
* temporary      - ``Artifact`` rows with ``is_temporary=True`` expire via the retention sweeper
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, UTCDateTime, utcnow


class Role(str, enum.Enum):
    USER = "USER"
    ANALYST = "ANALYST"
    ADMIN = "ADMIN"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=16), default=Role.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Bumped on password change / forced logout; embedded in access tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=0)

    sessions: Mapped[list[RefreshSession]] = relationship(back_populates="user", cascade="all, delete-orphan")


class RefreshSession(Base):
    """Server-side refresh-token record. Only a SHA-256 of the token is stored."""

    __tablename__ = "refresh_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class AnalysisRecord(Base):
    __tablename__ = "analysis_records"
    __table_args__ = (Index("ix_analysis_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="steganalysis")  # steganalysis|forensics|attack|demo
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    image_format: Mapped[str] = mapped_column(String(16), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    file_size: Mapped[int] = mapped_column(Integer, default=0)

    prediction: Mapped[str] = mapped_column(String(16))  # cover|stego
    confidence: Mapped[float] = mapped_column(Float)
    predicted_technique: Mapped[str] = mapped_column(String(16))  # normal|lsb|dct|dwt
    probabilities: Mapped[dict[str, Any]] = mapped_column(JSONType)
    rf_probabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(16))
    risk_factors: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    payload_signature: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    model_name: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(32))
    inference_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tiles: Mapped[int] = mapped_column(Integer, default=1)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Summary used by reports (explanation, top features, forensic findings) - never pixel data.
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class StegoOperation(Base):
    __tablename__ = "stego_operations"
    __table_args__ = (Index("ix_stegoop_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    operation: Mapped[str] = mapped_column(String(16))  # embed|extract
    algorithm: Mapped[str] = mapped_column(String(16))  # lsb|dct|dwt
    payload_kind: Mapped[str] = mapped_column(String(8), default="text")  # text|file
    payload_size: Mapped[int] = mapped_column(Integer, default=0)  # plaintext bytes
    envelope_size: Mapped[int] = mapped_column(Integer, default=0)  # encrypted bytes embedded
    image_width: Mapped[int] = mapped_column(Integer, default=0)
    image_height: Mapped[int] = mapped_column(Integer, default=0)
    image_size: Mapped[int] = mapped_column(Integer, default=0)  # file bytes
    capacity_bytes: Mapped[int] = mapped_column(Integer, default=0)
    utilization: Mapped[float | None] = mapped_column(Float, nullable=True)
    psnr: Mapped[float | None] = mapped_column(Float, nullable=True)
    ssim: Mapped[float | None] = mapped_column(Float, nullable=True)
    mse: Mapped[float | None] = mapped_column(Float, nullable=True)
    kdf: Mapped[str] = mapped_column(String(16), default="argon2id")
    cover_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stego_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    envelope_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class AttackExperiment(Base):
    __tablename__ = "attack_experiments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    source_image: Mapped[str] = mapped_column(String(64))  # SHA-256 of the attacked stego image
    source_filename: Mapped[str] = mapped_column(String(255), default="")
    algorithm: Mapped[str | None] = mapped_column(String(16), nullable=True)
    attack_type: Mapped[str] = mapped_column(String(32))
    attack_parameters: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    detection_probability_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    detection_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_technique: Mapped[str | None] = mapped_column(String(16), nullable=True)
    extraction_success: Mapped[bool] = mapped_column(Boolean, default=False)
    integrity_status: Mapped[str] = mapped_column(String(16))  # verified|failed|not_found
    decryption_status: Mapped[str] = mapped_column(String(16), default="not_attempted")
    bit_error_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    psnr: Mapped[float | None] = mapped_column(Float, nullable=True)
    ssim: Mapped[float | None] = mapped_column(Float, nullable=True)
    mse: Mapped[float | None] = mapped_column(Float, nullable=True)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("model_name", "version", name="uq_model_name_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    model_name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(24))  # cnn|random_forest
    framework: Mapped[str] = mapped_column(String(32))
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    f1: Mapped[float | None] = mapped_column(Float, nullable=True)
    roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    artifact_path: Mapped[str] = mapped_column(String(512))
    weights_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    trained_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_action_ts", "action", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    action: Mapped[str] = mapped_column(String(48))
    result: Mapped[str] = mapped_column(String(16))  # success|failure|denied
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    details: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)


class Artifact(Base):
    """Registry of generated files (stego images, heatmaps, attacked images, reports)."""

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    rel_path: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_records.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200))
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"))
    sha256: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))  # technique_comparison|robustness_batch
    status: Mapped[str] = mapped_column(String(16), default="completed")
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    results: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(254), nullable=True)
