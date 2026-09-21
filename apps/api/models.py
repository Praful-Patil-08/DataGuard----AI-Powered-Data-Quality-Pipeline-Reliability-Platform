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
    scans = relationship("Scan", foreign_keys="[Scan.dataset_id]", back_populates="dataset", cascade="all, delete-orphan")


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
    # Adapted from Watchtower: extended profiling fields for drift detection
    null_rate = Column(Float, default=0.0)
    unique_ratio = Column(Float, default=0.0)
    # Numeric statistics (only for INTEGER/FLOAT columns) - IQR-based outlier detection
    min_value = Column(Float, nullable=True)
    max_value = Column(Float, nullable=True)
    mean = Column(Float, nullable=True)
    median = Column(Float, nullable=True)
    p05 = Column(Float, nullable=True)
    p95 = Column(Float, nullable=True)
    outlier_count = Column(Integer, nullable=True, default=0)
    outlier_rate = Column(Float, nullable=True, default=0.0)
    top_values = Column(JSON, default=list)

    schema_rel = relationship("SchemaRecord", back_populates="columns")


class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    baseline_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True)
    status = Column(String(50), default="COMPLETED")  # RUNNING, COMPLETED, FAILED
    healthy_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)
    incident_summary = Column(Text, nullable=True)
    incident_severity = Column(String(20), nullable=True)  # INFO/WARNING/CRITICAL/PASSED
    # Phase 3: deterministic quality score 0-100 with explainable dimensions
    quality_score = Column(Float, nullable=True, default=100.0)
    quality_dimensions = Column(JSON, default=dict)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, default=datetime.datetime.utcnow)

    dataset = relationship("Dataset", foreign_keys=[dataset_id], back_populates="scans")
    baseline_dataset = relationship("Dataset", foreign_keys=[baseline_dataset_id])
    issues = relationship("Issue", back_populates="scan", cascade="all, delete-orphan")
    ai_analyses = relationship("AIAnalysis", back_populates="scan", cascade="all, delete-orphan")
    remediations = relationship("Remediation", back_populates="scan", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="scan", cascade="all, delete-orphan")


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
    technical_impact = Column(Text, nullable=True)
    business_impact = Column(Text, nullable=True)
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


class QualityContract(Base):
    """
    Declarative data-quality contract — SodaCL / GE expectation inspired.
    Owns the expectation, not the scan result.
    Versioned via `version` int, soft history via updated_at.
    """
    __tablename__ = "quality_contracts"

    id = Column(Integer, primary_key=True, index=True)
    dataset_name = Column(String(255), nullable=False, index=True)  # logical name e.g., orders
    column_name = Column(String(255), nullable=True, index=True)    # None for table-level (row_count)
    contract_type = Column(String(50), nullable=False, index=True)  # completeness|uniqueness|range|regex|row_count
    # threshold is completeness/uniqueness/validity ratio 0.0-1.0; for row_count params contains min/max
    threshold = Column(Float, nullable=True)
    params = Column(JSON, default=dict)  # extra: {min, max, pattern, etc}
    severity = Column(String(20), default="WARNING", nullable=False)
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))


class Baseline(Base):
    """
    Baseline snapshot — explicit, versioned, never silent.

    Represents a dataset's known-good state:
    - logical dataset_name (e.g., orders)
    - physical baseline_dataset_id + baseline_schema_id + fingerprint
    - profiling snapshot (row_count, column_count, schema columns via FK)
    - quality metrics snapshot (quality_score at creation time via latest scan, if any)
    - distribution snapshot (via schema columns stats)
    - timestamp/version, is_active (only one active per logical dataset)

    Never silently updated after scan — must be explicitly created/activated.
    """
    __tablename__ = "baselines"

    id = Column(Integer, primary_key=True, index=True)
    dataset_name = Column(String(255), nullable=False, index=True)  # logical name
    baseline_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    baseline_schema_id = Column(Integer, ForeignKey("schemas.id"), nullable=True, index=True)
    fingerprint = Column(String(64), nullable=False, index=True)
    row_count = Column(Integer, default=0)
    column_count = Column(Integer, default=0)
    quality_score = Column(Float, nullable=True)  # snapshot at creation time
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_by = Column(String(255), nullable=True, default="system")
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

    baseline_dataset = relationship("Dataset", foreign_keys=[baseline_dataset_id])
    baseline_schema = relationship("SchemaRecord", foreign_keys=[baseline_schema_id])


class Incident(Base):
    """
    Incident — correlated grouping of related issues (deterministic).

    Example: "Customer ingestion pipeline degraded" groups:
    - customer_id null_rate drift
    - row_count drop
    - schema change
    - downstream orders affected

    Deterministic correlation via evidence: same scan, same dataset,
    column overlap, issue_type families (schema, drift, quality, contract,
    statistical), and downstream lineage overlap.

    One incident per scan for MVP (all related issues grouped), with
    deterministic ID and explainable grouping metadata. Future: multiple
    incidents per scan if distinct columns/KPIs.
    """
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    # Logical dataset name for cross-version grouping
    dataset_name = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    severity = Column(String(20), nullable=False, index=True)  # INFO/WARNING/CRITICAL
    status = Column(String(20), default="OPEN", nullable=False, index=True)  # OPEN, INVESTIGATING, RESOLVED, CLOSED
    root_cause = Column(Text, nullable=True)  # deterministic hypothesis
    affected_columns = Column(JSON, default=list)  # list of column names
    affected_assets = Column(JSON, default=list)  # downstream assets from lineage
    issue_ids = Column(JSON, default=list)  # list of Issue ids in this incident
    issue_types = Column(JSON, default=list)  # distinct issue_type list
    issue_count = Column(Integer, default=0)
    # Evidence for correlation: shared columns, shared families, lineage overlap
    correlation_evidence = Column(JSON, default=dict)
    quality_score_at_incident = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(255), nullable=True)

    scan = relationship("Scan", foreign_keys=[scan_id], back_populates="incidents")
    dataset = relationship("Dataset", foreign_keys=[dataset_id])


class LineageEdge(Base):
    """
    Lineage edge — dataset/column -> dataset/column via job/run.

    Inspired by OpenLineage (Dataset/Job/Run) + Marquez (lineage storage/API):
    - source: dataset + column (column nullable for dataset-level)
    - target: dataset/job/dashboard + column
    - job/run metadata for pipeline execution lineage
    - relationship: DIRECT_INPUT, TRANSFORMED, AGGREGATION, etc.
    - Deterministic, versioned via created_at, is_active soft-delete.

    Example:
        orders.order_value --[revenue_pipeline#42]--> revenue_model --[rollup]--> Executive Dashboard
    """
    __tablename__ = "lineage_edges"

    id = Column(Integer, primary_key=True, index=True)
    source_dataset = Column(String(255), nullable=False, index=True)  # e.g., orders
    source_column = Column(String(255), nullable=True, index=True)  # e.g., order_value, None for dataset-level
    target_dataset = Column(String(255), nullable=False, index=True)  # e.g., revenue_model
    target_column = Column(String(255), nullable=True, index=True)  # optional column in target
    target_type = Column(String(50), default="DATASET", nullable=False, index=True)  # DATASET, JOB, SQL_MODEL, DASHBOARD
    job_name = Column(String(255), nullable=True, index=True)  # e.g., revenue_pipeline
    run_id = Column(String(100), nullable=True, index=True)  # e.g., run_42
    relationship = Column(String(50), default="DIRECT", nullable=False)  # DIRECT, TRANSFORMED, AGGREGATION
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_by = Column(String(255), nullable=True, default="system")
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))


class AuditLog(Base):
    """
    Audit trail — who, what, when, why, previous state, new state.

    Every important action is traceable:
    - baseline changes
    - contract changes (create/update/delete)
    - remediation approvals/rejections
    - incident status changes
    - AI analysis
    - lineage edge changes
    - scan creation
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(100), nullable=False, index=True)  # e.g., baseline.create, contract.update, remediation.approve
    actor = Column(String(255), nullable=False, default="system", index=True)  # who
    target_type = Column(String(50), nullable=False, index=True)  # baseline, contract, remediation, incident, ai_analysis, scan, lineage_edge
    target_id = Column(String(100), nullable=True, index=True)  # id as string (supports composite)
    previous_state = Column(JSON, nullable=True)
    new_state = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)  # why (notes)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)
