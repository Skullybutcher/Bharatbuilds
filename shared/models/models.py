"""Typed data-model additions (Spec 57D): ImpactSummary, RuleReview, Approval,
BenchmarkRun, BenchmarkCaseResult. Storage lives in services/storage.py."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ImpactSummary:
    impact_summary_id: str
    build_id: str
    semantic_changes: int
    artifact_counts: dict = field(default_factory=dict)
    behavioral_counts: dict = field(default_factory=dict)
    test_cohort_counts: dict = field(default_factory=dict)
    verification_counts: dict = field(default_factory=dict)
    created_at: float = 0.0


@dataclass
class RuleReview:
    review_id: str
    rule_id: str
    build_id: str
    reviewer_id: str = ""
    decision: str = "PENDING"  # PENDING|ACCEPT|EDIT|REJECT|ESCALATE
    machine_value: dict = field(default_factory=dict)
    human_value: dict | None = None
    reason: str | None = None
    timestamp: float | None = None


@dataclass
class Approval:
    approval_id: str
    build_id: str
    patch_id: str = ""
    procedure_version_candidate: str = ""
    reviewer_id: str = ""
    role: str = ""  # POLICY_REVIEWER|PROCEDURE_OWNER|FINAL_APPROVER
    decision: str = ""
    reason: str = ""
    artifact_hashes: dict = field(default_factory=dict)
    timestamp: float | None = None


@dataclass
class BenchmarkRun:
    benchmark_run_id: str
    benchmark_version: str
    compiler_version: str
    extractor_version: str
    manifest_hash: str
    started_at: float = 0.0
    completed_at: float = 0.0
    metrics: dict = field(default_factory=dict)


@dataclass
class BenchmarkCaseResult:
    benchmark_run_id: str
    case_id: str
    status: str  # AUTO_REPAIRED|CORRECTLY_NO_OP|CORRECTLY_ESCALATED|UNSUPPORTED|FAILED_*
    extraction_result: dict = field(default_factory=dict)
    delta_result: dict = field(default_factory=dict)
    witness_result: dict = field(default_factory=dict)
    localization_result: dict = field(default_factory=dict)
    patch_result: dict = field(default_factory=dict)
    preservation_result: dict = field(default_factory=dict)
    latency: dict = field(default_factory=dict)
