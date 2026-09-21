from typing import List, Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, ConfigDict

# --- Dataset Schemas ---
class DatasetBase(BaseModel):
    name: str
    filename: str
    file_type: str

class DatasetResponse(DatasetBase):
    id: int
    row_count: int
    column_count: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class DatasetUploadResponse(BaseModel):
    dataset_id: int
    filename: str
    row_count: int
    column_count: int

# --- Schema & Column Schemas ---
class SchemaColumnResponse(BaseModel):
    id: int
    column_name: str
    data_type: str
    nullable: bool
    unique_count: int
    null_count: int
    sample_values: List[Any] = []
    # Watchtower-adapted extended profiling
    null_rate: float = 0.0
    unique_ratio: float = 0.0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    p05: Optional[float] = None
    p95: Optional[float] = None
    outlier_count: Optional[int] = 0
    outlier_rate: Optional[float] = 0.0
    top_values: List[Any] = []
    model_config = ConfigDict(from_attributes=True)

class SchemaResponse(BaseModel):
    id: int
    dataset_id: int
    fingerprint: str
    created_at: datetime
    columns: List[SchemaColumnResponse] = []
    model_config = ConfigDict(from_attributes=True)

from pydantic import BaseModel, ConfigDict, Field

# --- Issue Schemas ---
class IssueResponse(BaseModel):
    id: int
    scan_id: int
    issue_type: str
    severity: str
    column_name: Optional[str] = None
    description: str
    issue_metadata: Dict[str, Any] = Field(default_factory=dict, validation_alias="issue_metadata", serialization_alias="metadata")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

# --- AI Analysis Schemas ---
class AIAnalysisRequest(BaseModel):
    pass

class AIAnalysisResponse(BaseModel):
    id: Optional[int] = None
    scan_id: int
    summary: str
    severity: str
    root_cause: str
    impact: str
    technical_impact: Optional[str] = None
    business_impact: Optional[str] = None
    affected_assets: List[str] = []
    recommended_action: str
    confidence: float
    requires_human_approval: bool = True
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

# --- Remediation Schemas ---
class RemediationActionRequest(BaseModel):
    decision_by: Optional[str] = "analyst@dataguard.internal"
    notes: Optional[str] = None

class RemediationResponse(BaseModel):
    id: int
    scan_id: int
    suggestion: str
    status: str
    decision_by: Optional[str] = None
    decision_at: Optional[datetime] = None
    notes: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

# --- Scan Schemas ---
class ScanResponse(BaseModel):
    id: int
    dataset_id: int
    baseline_dataset_id: Optional[int] = None
    status: str
    healthy_count: int
    warning_count: int
    critical_count: int
    incident_summary: Optional[str] = None
    incident_severity: Optional[str] = None
    started_at: datetime
    completed_at: datetime
    issues: List[IssueResponse] = []
    ai_analyses: List[AIAnalysisResponse] = []
    remediations: List[RemediationResponse] = []
    model_config = ConfigDict(from_attributes=True)

class GateResponse(BaseModel):
    passed: bool
    reasons: List[str] = []
    allowed_severity: str
    max_row_count_drop_ratio: float
    max_null_drift_count: int
    max_numeric_drift_count: int
    max_cardinality_drift_count: int
    incident_severity: str

class DatasetHistoryResponse(BaseModel):
    dataset_id: int
    dataset_name: str
    scans: List[ScanResponse] = []

class ReliabilityTrendPoint(BaseModel):
    date: str
    healthy: int
    warning: int
    critical: int
    total: int

class TopIssueResponse(BaseModel):
    scan_id: int
    dataset_id: int
    dataset_name: str
    filename: str
    severity: str
    issue_type: str
    column_name: Optional[str] = None
    description: str
    created_at: datetime

class BusinessImpactResponse(BaseModel):
    kpi: str
    status: str  # HEALTHY, AT RISK, CRITICAL
    affected_datasets: List[str] = []
    affected_columns: List[str] = []
    description: str

# --- Lineage & Impact Schemas ---
class DownstreamAsset(BaseModel):
    name: str
    asset_type: str # SQL_MODEL, DASHBOARD
    relationship: str

class ColumnImpactResponse(BaseModel):
    column_name: str
    dataset_name: str
    affected_assets: List[DownstreamAsset] = []
    is_demo: bool = True
    demo_note: str = "Static demo lineage from lineage.py — replace with OpenLineage/dbt in production."

# --- Quality Contract Schemas ---
class QualityContractCreate(BaseModel):
    dataset_name: str
    column_name: Optional[str] = None
    contract_type: str  # completeness|uniqueness|range|regex|row_count (aliases: not_null, unique)
    threshold: Optional[float] = None  # 0.0-1.0 validity ratio; None for row_count uses params
    params: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "WARNING"  # CRITICAL|WARNING|INFO
    description: Optional[str] = None
    enabled: bool = True

class QualityContractUpdate(BaseModel):
    dataset_name: Optional[str] = None
    column_name: Optional[str] = None
    contract_type: Optional[str] = None
    threshold: Optional[float] = None
    params: Optional[Dict[str, Any]] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None

class QualityContractResponse(BaseModel):
    id: int
    dataset_name: str
    column_name: Optional[str] = None
    contract_type: str
    threshold: Optional[float] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    severity: str
    description: Optional[str] = None
    enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Health Schema ---
class HealthResponse(BaseModel):
    status: str
    database: str
    timestamp: datetime
