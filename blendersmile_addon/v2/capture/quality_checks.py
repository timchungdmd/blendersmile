"""Quality check framework for scan and photo imports."""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class Severity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class QualityIssue:
    severity: Severity
    message: str
    suggestion: Optional[str] = None
    object_name: Optional[str] = None


class ScanQualityChecker:
    def __init__(
        self,
        min_vertices: int = 1000,
        max_holes: int = 10,
        check_manifold: bool = True,
    ):
        self.min_vertices = min_vertices
        self.max_holes = max_holes
        self.check_manifold = check_manifold

    def check(self, mesh) -> List[QualityIssue]:
        issues = []

        if hasattr(mesh, "vertices"):
            n_verts = len(mesh.vertices)
            if n_verts < self.min_vertices:
                issues.append(
                    QualityIssue(
                        severity=Severity.INFO,
                        message=f"Low vertex count: {n_verts} (expected >{self.min_vertices})",
                        suggestion="Consider rescanning with higher resolution",
                    )
                )

        try:
            if hasattr(mesh, "vertices") and len(mesh.vertices) > 0:
                if not hasattr(mesh.vertices[0], "normal"):
                    issues.append(
                        QualityIssue(
                            severity=Severity.WARNING,
                            message="Mesh missing vertex normals",
                            suggestion="Recalculate normals in Blender",
                        )
                    )
        except (AttributeError, IndexError):
            pass

        if hasattr(mesh, "loop_triangles"):
            n_faces = len(mesh.loop_triangles)
            n_verts = len(mesh.vertices) if hasattr(mesh, "vertices") else 0
            if n_verts > 0 and n_faces < n_verts * 0.5:
                issues.append(
                    QualityIssue(
                        severity=Severity.WARNING,
                        message="Mesh may have holes or missing faces",
                        suggestion="Inspect mesh in edit mode for holes",
                    )
                )

        return issues


class PhotoQualityChecker:
    def __init__(
        self,
        min_resolution: tuple = (800, 600),
        min_brightness: float = 0.2,
        max_brightness: float = 0.95,
    ):
        self.min_resolution = min_resolution
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness

    def check_brightness(
        self,
        image,
        min_brightness: Optional[float] = None,
    ) -> List[QualityIssue]:
        issues = []
        min_b = min_brightness or self.min_brightness

        if image is None:
            issues.append(
                QualityIssue(
                    severity=Severity.ERROR,
                    message="Empty or invalid image",
                )
            )
            return issues

        try:
            import numpy as np

            if len(image.shape) == 3:
                gray = np.mean(image, axis=2)
            else:
                gray = image
            avg_brightness = np.mean(gray) / 255.0

            if avg_brightness < min_b:
                issues.append(
                    QualityIssue(
                        severity=Severity.WARNING,
                        message=f"Image underexposed (brightness: {avg_brightness:.2f})",
                        suggestion="Use better lighting or enable adaptive lighting correction",
                    )
                )
            elif avg_brightness > self.max_brightness:
                issues.append(
                    QualityIssue(
                        severity=Severity.WARNING,
                        message=f"Image overexposed (brightness: {avg_brightness:.2f})",
                        suggestion="Reduce lighting or camera exposure",
                    )
                )
        except ImportError:
            pass

        return issues

    def check_resolution(self, image) -> List[QualityIssue]:
        issues = []
        if image is None:
            return issues

        try:
            h, w = image.shape[:2]
            min_w, min_h = self.min_resolution

            if w < min_w or h < min_h:
                issues.append(
                    QualityIssue(
                        severity=Severity.INFO,
                        message=f"Low resolution: {w}x{h} (expected >{min_w}x{min_h})",
                        suggestion="Use higher resolution camera for better quality",
                    )
                )
        except (AttributeError, IndexError):
            pass

        return issues

    def check(self, image) -> List[QualityIssue]:
        issues = []
        issues.extend(self.check_brightness(image))
        issues.extend(self.check_resolution(image))
        return issues
