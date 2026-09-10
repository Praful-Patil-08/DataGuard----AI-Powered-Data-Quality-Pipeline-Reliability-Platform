import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Float,
    Text,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from database import Base

class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    row_count = Column(Integer, default=0)
    column_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    schemas = relationship("SchemaRecord", back_populates="dataset", cascade="all, delete-orphan")
    scans = relationship("Scan", back_populates="dataset", cascade="all, delete-orphan")


class SchemaRecord(Base):
    __tablename__ = "schemas"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    fingerprint = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    dataset = relationship("Dataset", back_populates="schemas")
    columns = relationship("SchemaColumn", back_populates="schema_rel", cascade="all, delete-orphan")


class SchemaColumn(Base):
    __tablename__ = "schema_columns"

    id = Column(Integer, primary_key=True, index=True)
    schema_id = Column(Integer, ForeignKey("schemas.id"), nullable=False)
    column_name = Column(String(255), nullable=False)
    data_type = Column(String(50), nullable=False)
    nullable = Column(Boolean, default=True)
    unique_count = Column(Integer, default=0)
    null_count = Column(Integer, default=0)
    sample_values = Column(JSON, default=list)

    schema_rel = relationship("SchemaRecord", back_populates="columns")


class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    status = Column(String(50), default="COMPLETED")  # RUNNING, COMPLETED, FAILED
    healthy_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, default=datetime.datetime.utcnow)

    dataset = relationship("Dataset", back_populates="scans")
    issues = relationship("Issue", back_populates="scan", cascade="all, delete-orphan")
    ai_analyses = relationship("AIAnalysis", back_populates="scan", cascade="all, delete-orphan")
    remediations = relationship("Remediation", back_populates="scan", cascade="all, delete-orphan")


class Issue(Base):
    __tablename__ = "issues"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)
    issue_type = Column(String(100), nullable=False)  # COLUMN_REMOVED, TYPE_CHANGED, NULL_CHECK, etc.
    severity = Column(String(20), nullable=False)    # CRITICAL, WARNING, INFO
    column_name = Column(String(255), nullable=True)
    description = Column(Text, nullable=False)
    issue_metadata = Column("metadata", JSON, default=dict)

    scan = relationship("Scan", back_populates="issues")


class AIAnalysis(Base):
    __tablename__ = "ai_analysis"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)
    severity = Column(String(20), default="WARNING")
    summary = Column(Text, nullable=False)
    root_cause = Column(Text, nullable=False)
    impact = Column(Text, nullable=False)
    affected_assets = Column(JSON, default=list)
    recommended_action = Column(Text, nullable=False)
    confidence = Column(Float, default=0.90)
    requires_human_approval = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    scan = relationship("Scan", back_populates="ai_analyses")


class Remediation(Base):
    __tablename__ = "remediations"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)
    suggestion = Column(Text, nullable=False)
    status = Column(String(50), default="PENDING")  # PENDING, APPROVED, REJECTED
    decision_by = Column(String(255), nullable=True)
    decision_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    scan = relationship("Scan", back_populates="remediations")


class Dependency(Base):
    __tablename__ = "dependencies"

    id = Column(Integer, primary_key=True, index=True)
    source_asset = Column(String(255), nullable=False, index=True)  # e.g., orders.order_value
    target_asset = Column(String(255), nullable=False, index=True)  # e.g., revenue_model
    relationship_type = Column(String(50), nullable=False)           # DERIVED_BY, DASHBOARD_FEED, etc.
    target_type = Column(String(50), default="SQL_MODEL")            # SQL_MODEL, DASHBOARD
