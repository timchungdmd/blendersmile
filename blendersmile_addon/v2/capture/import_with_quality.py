"""Import operators with integrated quality checks."""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from .quality_checks import (
    ScanQualityChecker,
    PhotoQualityChecker,
    QualityIssue,
    Severity,
)


@dataclass
class ImportResult:
    success: bool
    object: Optional[Any] = None
    quality_issues: List[QualityIssue] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.quality_issues is None:
            self.quality_issues = []


def import_scan_with_quality_check(
    filepath: str,
    mesh_mock=None,
    checker: Optional[ScanQualityChecker] = None,
) -> Dict[str, Any]:
    import bpy

    issues = []
    obj = None

    try:
        ext = filepath.lower().split(".")[-1]

        if ext == "stl":
            bpy.ops.import_mesh.stl(filepath=filepath)
        elif ext == "obj":
            bpy.ops.import_scene.obj(filepath=filepath)
        elif ext == "ply":
            bpy.ops.import_mesh.ply(filepath=filepath)
        else:
            return ImportResult(
                success=False, error_message=f"Unsupported format: {ext}"
            ).__dict__

        obj = bpy.context.selected_objects[-1] if bpy.context.selected_objects else None

        if obj is None:
            return ImportResult(
                success=False, error_message="No object imported"
            ).__dict__

        if checker is None:
            checker = ScanQualityChecker()

        mesh_to_check = mesh_mock if mesh_mock else obj.data
        issues = checker.check(mesh_to_check)

        return ImportResult(
            success=True,
            object=obj,
            quality_issues=issues,
        ).__dict__

    except Exception as e:
        return ImportResult(
            success=False,
            error_message=str(e),
            quality_issues=issues,
        ).__dict__


def format_quality_report(issues: List[QualityIssue]) -> str:
    if not issues:
        return "Quality check passed"

    lines = ["Quality Issues Detected:"]
    for issue in issues:
        icon = {
            Severity.ERROR: "[ERROR]",
            Severity.WARNING: "[WARN]",
            Severity.INFO: "[INFO]",
        }.get(issue.severity, "[-]")

        lines.append(f"  {icon} {issue.message}")
        if issue.suggestion:
            lines.append(f"      Suggestion: {issue.suggestion}")

    return "\n".join(lines)
