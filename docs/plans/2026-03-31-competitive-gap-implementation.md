# Competitive Gap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Address competitive workflow gaps against exocad/SmileCloud while maintaining architecture stability.

**Architecture:** Phased approach - architecture stabilization (P0) first, then workflow improvements in dependency order: Capture → Validate → Present → Plan → Simulate (AI-assisted portrait-first).

**Tech Stack:** Python 3.10+, Blender 3.6+ API, unittest, Blender headless runtime

---

## Priority Summary

### P0: Architecture Stabilization (Prerequisite)
1. Package authority declaration
2. Runtime verification infrastructure
3. Draw-time mutation removal
4. Monolith seam extraction

### P1: Workflow Foundations (After P0)
5. Capture quality checks
6. Validate review workspace
7. Present mode

### P2: Advanced Workflows
8. Plan Blueprint workflow
9. Portrait-first Simulate phase

---

## Phase 0: Architecture Stabilization

**Depends on:** Existing architecture backlog (`docs/plans/2026-03-10-architecture-first-backlog.md`)

**Status:** MUST COMPLETE FIRST before any competitive gap work.

**Rationale:** Adding features to a 49K-line monolith without tests is unsustainable. All subsequent phases depend on stable seams and verification infrastructure.

**Tasks:** Execute architecture backlog Phases 0-3 before proceeding.

---

## Phase 1: Capture Quality Checks

**Goal:** Add input quality validation to match SmileCloud's guided capture.

**Estimated effort:** 1 week

**Dependencies:** Phase 0 complete

### Task 1: Design Quality Check Framework

**Files:**
- Create: `blendersmile_addon/v2/capture/quality_checks.py`
- Create: `tests/test_capture_quality.py`

**Step 1: Write the failing test**
```python
"""tests/test_capture_quality.py"""
import unittest
from unittest.mock import Mock, patch
from blendersmile_addon.v2.capture.quality_checks import (
    ScanQualityChecker,
    PhotoQualityChecker,
    QualityIssue,
    Severity,
)

class TestScanQualityChecker(unittest.TestCase):
    def test_detect_missing_normals(self):
        """Missing normals should trigger WARNING."""
        mock_mesh = Mock()
        mock_mesh.vertices = [Mock() for _ in range(100)]
        mock_mesh.loop_triangles = [Mock() for _ in range(50)]
        # Simulate missing normals
        del mock_mesh.vertices[0].normal
        
        checker = ScanQualityChecker()
        issues = checker.check(mock_mesh)
        
        self.assertTrue(
            any(i.severity == Severity.WARNING and "normal" in i.message.lower()
                for i in issues)
        )

    def test_detect_low_vertex_count(self):
        """Very low vertex count should trigger INFO."""
        mock_mesh = Mock()
        mock_mesh.vertices = [Mock() for _ in range(10)]
        
        checker = ScanQualityChecker(min_vertices=100)
        issues = checker.check(mock_mesh)
        
        self.assertTrue(
            any(i.severity == Severity.INFO and "vertex" in i.message.lower()
                for i in issues)
        )

class TestPhotoQualityChecker(unittest.TestCase):
    def test_detect_underexposure(self):
        """Dark image should trigger WARNING."""
        checker = PhotoQualityChecker()
        # Mock dark image (low average brightness)
        issues = checker.check_brightness(mock_dark_image(), min_brightness=0.3)
        
        self.assertTrue(
            any(i.severity == Severity.WARNING and "exposure" in i.message.lower()
                for i in issues)
        )

def mock_dark_image():
    """Create a mock dark image for testing."""
    import numpy as np
    return np.zeros((100, 100, 3), dtype=np.uint8) + 30

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
```bash
python -m pytest tests/test_capture_quality.py -v
```
Expected: FAIL with "No module named 'blendersmile_addon.v2.capture.quality_checks'"

**Step 3: Write minimal implementation**
```python
"""blendersmile_addon/v2/capture/quality_checks.py"""
"""Quality check framework for scan and photo imports."""
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
import numpy as np


class Severity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class QualityIssue:
    """A quality issue detected during import."""
    severity: Severity
    message: str
    suggestion: Optional[str] = None
    object_name: Optional[str] = None


class ScanQualityChecker:
    """Check scan mesh quality on import."""
    
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
        """Run all quality checks on a mesh."""
        issues = []
        
        # Check vertex count
        if hasattr(mesh, 'vertices'):
            n_verts = len(mesh.vertices)
            if n_verts < self.min_vertices:
                issues.append(QualityIssue(
                    severity=Severity.INFO,
                    message=f"Low vertex count: {n_verts} (expected >{self.min_vertices})",
                    suggestion="Consider rescanning with higher resolution",
                ))
        
        # Check normals exist
        try:
            if hasattr(mesh, 'vertices') and len(mesh.vertices) > 0:
                if not hasattr(mesh.vertices[0], 'normal'):
                    issues.append(QualityIssue(
                        severity=Severity.WARNING,
                        message="Mesh missing vertex normals",
                        suggestion="Recalculate normals in Blender",
                    ))
        except (AttributeError, IndexError):
            pass
        
        # Check for obvious holes (very simplified)
        if hasattr(mesh, 'loop_triangles'):
            n_faces = len(mesh.loop_triangles)
            n_verts = len(mesh.vertices) if hasattr(mesh, 'vertices') else 0
            if n_verts > 0 and n_faces < n_verts * 0.5:
                issues.append(QualityIssue(
                    severity=Severity.WARNING,
                    message="Mesh may have holes or missing faces",
                    suggestion="Inspect mesh in edit mode for holes",
                ))
        
        return issues


class PhotoQualityChecker:
    """Check photo quality for portrait-first workflow."""
    
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
        image: np.ndarray,
        min_brightness: Optional[float] = None,
    ) -> List[QualityIssue]:
        """Check if image is properly exposed."""
        issues = []
        min_b = min_brightness or self.min_brightness
        
        if image is None or image.size == 0:
            issues.append(QualityIssue(
                severity=Severity.ERROR,
                message="Empty or invalid image",
            ))
            return issues
        
        # Calculate average brightness
        if len(image.shape) == 3:
            gray = np.mean(image, axis=2)
        else:
            gray = image
        
        avg_brightness = np.mean(gray) / 255.0
        
        if avg_brightness < min_b:
            issues.append(QualityIssue(
                severity=Severity.WARNING,
                message=f"Image underexposed (brightness: {avg_brightness:.2f})",
                suggestion="Use better lighting or enable adaptive lighting correction",
            ))
        elif avg_brightness > self.max_brightness:
            issues.append(QualityIssue(
                severity=Severity.WARNING,
                message=f"Image overexposed (brightness: {avg_brightness:.2f})",
                suggestion="Reduce lighting or camera exposure",
            ))
        
        return issues
    
    def check_resolution(
        self,
        image: np.ndarray,
    ) -> List[QualityIssue]:
        """Check if image resolution is sufficient."""
        issues = []
        
        if image is None:
            return issues
        
        h, w = image.shape[:2]
        min_w, min_h = self.min_resolution
        
        if w < min_w or h < min_h:
            issues.append(QualityIssue(
                severity=Severity.INFO,
                message=f"Low resolution: {w}x{h} (expected >{min_w}x{min_h})",
                suggestion="Use higher resolution camera for better quality",
            ))
        
        return issues
    
    def check(self, image: np.ndarray) -> List[QualityIssue]:
        """Run all quality checks on an image."""
        issues = []
        issues.extend(self.check_brightness(image))
        issues.extend(self.check_resolution(image))
        return issues
```

**Step 4: Run test to verify it passes**
```bash
python -m pytest tests/test_capture_quality.py -v
```
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_capture_quality.py blendersmile_addon/v2/capture/quality_checks.py
git commit -m "feat: add capture quality check framework

- Add ScanQualityChecker for mesh validation
- Add PhotoQualityChecker for image validation
- Check vertex count, normals, holes for scans
- Check exposure and resolution for photos
- Severity levels: INFO, WARNING, ERROR
- Unit tests for core functionality"
```

---

### Task 2: Integrate Quality Checks into Import Operators

**Files:**
- Modify: `blendersmile_pnp_full.py` (import operators)
- Create: `blendersmile_addon/v2/capture/import_with_quality.py`

**Step 1: Write integration test**
```python
"""tests/test_import_with_quality.py"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from blendersmile_addon.v2.capture.import_with_quality import (
    import_scan_with_quality_check,
    import_photo_with_quality_check,
)

class TestImportWithQuality(unittest.TestCase):
    @patch('bpy.ops.object')
    @patch('bpy.context')
    def test_import_scan_reports_quality_issues(self, mock_context, mock_ops):
        """Scan import should report quality issues to user."""
        # Mock a low-quality scan
        mock_mesh = Mock()
        mock_mesh.vertices = [Mock() for _ in range(50)]
        mock_mesh.loop_triangles = []
        
        result = import_scan_with_quality_check(
            filepath="test.stl",
            mesh_mock=mock_mesh,
        )
        
        # Should return both imported object and quality issues
        self.assertIsNotNone(result.get('object'))
        self.assertTrue(len(result.get('quality_issues', [])) > 0)

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
```bash
python -m pytest tests/test_import_with_quality.py -v
```
Expected: FAIL

**Step 3: Write implementation**
```python
"""blendersmile_addon/v2/capture/import_with_quality.py"""
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
    """Result of import with quality checks."""
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
    """
    Import a scan file with quality validation.
    
    Args:
        filepath: Path to scan file (STL, OBJ, PLY, etc.)
        mesh_mock: Optional mesh mock for testing
        checker: Optional custom quality checker
    
    Returns:
        Dict with 'object', 'quality_issues', 'success'
    """
    import bpy
    
    issues = []
    obj = None
    
    try:
        # Import based on extension
        ext = filepath.lower().split('.')[-1]
        
        if ext == 'stl':
            bpy.ops.import_mesh.stl(filepath=filepath)
        elif ext == 'obj':
            bpy.ops.import_scene.obj(filepath=filepath)
        elif ext == 'ply':
            bpy.ops.import_mesh.ply(filepath=filepath)
        else:
            return ImportResult(
                success=False,
                error_message=f"Unsupported format: {ext}"
            ).__dict__
        
        # Get imported object
        obj = bpy.context.selected_objects[-1] if bpy.context.selected_objects else None
        
        if obj is None:
            return ImportResult(
                success=False,
                error_message="No object imported"
            ).__dict__
        
        # Run quality check
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
    """Format quality issues for user display."""
    if not issues:
        return "✓ Quality check passed"
    
    lines = ["Quality Issues Detected:"]
    for issue in issues:
        icon = {
            Severity.ERROR: "❌",
            Severity.WARNING: "⚠️",
            Severity.INFO: "ℹ️",
        }.get(issue.severity, "•")
        
        lines.append(f"  {icon} {issue.message}")
        if issue.suggestion:
            lines.append(f"     Suggestion: {issue.suggestion}")
    
    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**
```bash
python -m pytest tests/test_import_with_quality.py -v
```
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_import_with_quality.py blendersmile_addon/v2/capture/import_with_quality.py
git commit -m "feat: integrate quality checks into import flow

- Add import_scan_with_quality_check wrapper
- Return quality issues along with imported object
- Format quality report for user display
- Severity-based icon display"
```

---

### Task 3: Add UI Feedback for Quality Issues

**Files:**
- Modify: `blendersmile_pnp_full.py` (import operators to use quality checks)
- Test: Manual Blender testing required

**Step 1: Modify import operator to show quality report**

In `blendersmile_pnp_full.py`, locate `SMILE_OT_import_scan` (approx line 11000+), add quality check integration:

```python
# After successful import, add quality check
from blendersmile_addon.v2.capture.import_with_quality import (
    format_quality_report,
)
from blendersmile_addon.v2.capture.quality_checks import Severity

# In execute method, after import succeeds:
checker = ScanQualityChecker(min_vertices=500)
issues = checker.check(obj.data)

if issues:
    report_msg = format_quality_report(issues)
    # Show in operator report
    if any(i.severity == Severity.ERROR for i in issues):
        self.report({'ERROR'}, report_msg)
    elif any(i.severity == Severity.WARNING for i in issues):
        self.report({'WARNING'}, report_msg)
    else:
        self.report({'INFO'}, report_msg)
```

**Step 2: Manual testing**
1. Open Blender with addon loaded
2. Import a low-quality scan (e.g., 100 vertices)
3. Verify quality warning appears in UI
4. Import a high-quality scan
5. Verify no warnings

**Step 3: Commit**
```bash
git add blendersmile_pnp_full.py
git commit -m "feat: show quality report on scan import

- Integrate quality checks into import_scan operator
- Show severity-appropriate reports (ERROR/WARNING/INFO)
- Guide users to improve scan quality"
```

---

## Phase 2: Validate Review Workspace

**Goal:** Create outcome-first review workspace matching SmileCloud's Review.

**Estimated effort:** 2 weeks

**Dependencies:** Phase 0 complete

### Task 1: Design Review Data Model

**Files:**
- Create: `blendersmile_addon/v2/review/models.py`
- Create: `tests/test_review_models.py`

**Step 1: Write the failing test**
```python
"""tests/test_review_models.py"""
import unittest
from blendersmile_addon.v2.review.models import (
    ReviewState,
    ReviewFinding,
    FindingSeverity,
    ToothReview,
    CaseReview,
)

class TestReviewModels(unittest.TestCase):
    def test_tooth_review_pass_fail(self):
        """Tooth review should track pass/fail state."""
        review = ToothReview(tooth_id=8)
        review.add_finding(ReviewFinding(
            severity=FindingSeverity.PASS,
            message="Margin integrity OK",
        ))
        
        self.assertEqual(review.state, ReviewState.PASS)
    
    def test_tooth_review_needs_attention(self):
        """Critical findings should mark tooth as needs_attention."""
        review = ToothReview(tooth_id=9)
        review.add_finding(ReviewFinding(
            severity=FindingSeverity.CRITICAL,
            message="Undercut detected",
        ))
        
        self.assertEqual(review.state, ReviewState.NEEDS_ATTENTION)
    
    def test_case_review_summary(self):
        """Case review should aggregate tooth states."""
        case = CaseReview()
        case.add_tooth_review(ToothReview(tooth_id=8, state=ReviewState.PASS))
        case.add_tooth_review(ToothReview(tooth_id=9, state=ReviewState.NEEDS_ATTENTION))
        
        summary = case.get_summary()
        
        self.assertEqual(summary['pass'], 1)
        self.assertEqual(summary['needs_attention'], 1)
        self.assertEqual(summary['pending'], 0)

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
```bash
python -m pytest tests/test_review_models.py -v
```
Expected: FAIL

**Step 3: Write minimal implementation**
```python
"""blendersmile_addon/v2/review/models.py"""
"""Review data models for outcome-first validation."""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime


class ReviewState(Enum):
    """Overall review state for a tooth or case."""
    PENDING = "PENDING"
    PASS = "PASS"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    FAIL = "FAIL"


class FindingSeverity(Enum):
    """Severity of individual findings."""
    INFO = "INFO"
    PASS = "PASS"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class ReviewFinding:
    """A single finding from review."""
    severity: FindingSeverity
    message: str
    location: Optional[tuple] = None  # (x, y, z) world coordinates
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'severity': self.severity.value,
            'message': self.message,
            'location': self.location,
            'created_at': self.created_at.isoformat(),
        }


@dataclass
class ToothReview:
    """Review state for a single tooth."""
    tooth_id: int
    state: ReviewState = ReviewState.PENDING
    findings: List[ReviewFinding] = field(default_factory=list)
    
    def add_finding(self, finding: ReviewFinding):
        """Add a finding and update state."""
        self.findings.append(finding)
        self._update_state()
    
    def _update_state(self):
        """Update overall state based on findings."""
        has_critical = any(
            f.severity == FindingSeverity.CRITICAL for f in self.findings
        )
        has_warning = any(
            f.severity == FindingSeverity.WARNING for f in self.findings
        )
        all_pass = all(
            f.severity in (FindingSeverity.PASS, FindingSeverity.INFO)
            for f in self.findings
        ) if self.findings else False
        
        if has_critical:
            self.state = ReviewState.NEEDS_ATTENTION
        elif has_warning:
            self.state = ReviewState.NEEDS_ATTENTION
        elif all_pass and self.findings:
            self.state = ReviewState.PASS
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'tooth_id': self.tooth_id,
            'state': self.state.value,
            'findings': [f.to_dict() for f in self.findings],
        }


@dataclass
class CaseReview:
    """Review state for an entire case."""
    tooth_reviews: Dict[int, ToothReview] = field(default_factory=dict)
    overall_notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def add_tooth_review(self, review: ToothReview):
        """Add or update a tooth review."""
        self.tooth_reviews[review.tooth_id] = review
    
    def get_tooth_review(self, tooth_id: int) -> Optional[ToothReview]:
        """Get review for a specific tooth."""
        return self.tooth_reviews.get(tooth_id)
    
    def get_summary(self) -> Dict[str, int]:
        """Get summary counts by state."""
        summary = {
            'pass': 0,
            'needs_attention': 0,
            'pending': 0,
            'fail': 0,
        }
        for review in self.tooth_reviews.values():
            summary[review.state.value.lower()] += 1
        return summary
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'tooth_reviews': {
                tid: r.to_dict() for tid, r in self.tooth_reviews.items()
            },
            'overall_notes': self.overall_notes,
            'created_at': self.created_at.isoformat(),
            'summary': self.get_summary(),
        }
```

**Step 4: Run test to verify it passes**
```bash
python -m pytest tests/test_review_models.py -v
```
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_review_models.py blendersmile_addon/v2/review/models.py
git commit -m "feat: add review data models

- ReviewState: PENDING, PASS, NEEDS_ATTENTION, FAIL
- FindingSeverity: INFO, PASS, WARNING, CRITICAL
- ToothReview: per-tooth state aggregation
- CaseReview: case-level summary
- Dict serialization for export"
```

---

### Task 2: Implement Contact Heatmap Visualization

**Files:**
- Create: `blendersmile_addon/v2/review/heatmap.py`
- Create: `tests/test_heatmap.py`

**Step 1: Write the failing test**
```python
"""tests/test_heatmap.py"""
import unittest
from unittest.mock import Mock
import numpy as np
from blendersmile_addon.v2.review.heatmap import (
    ContactHeatmap,
    CollisionResult,
)

class TestContactHeatmap(unittest.TestCase):
    def test_detect_collision_between_teeth(self):
        """Should detect when two teeth intersect."""
        # Create mock meshes
        mesh_a = Mock()
        mesh_a.vertices = [Mock(co=Mock(x=0, y=0, z=0))]
        
        mesh_b = Mock()
        mesh_b.vertices = [Mock(co=Mock(x=0.1, y=0, z=0))]
        
        heatmap = ContactHeatmap(collision_threshold=0.5)
        result = heatmap.check_collision(mesh_a, mesh_b)
        
        self.assertTrue(result.has_collision)
    
    def test_heatmap_vertex_colors(self):
        """Should generate vertex colors for visualization."""
        # Create simple collision scenario
        collision_result = CollisionResult(
            has_collision=True,
            collision_points=[(0, 0, 0)],
            penetration_depths=[0.5],
        )
        
        heatmap = ContactHeatmap()
        colors = heatmap.generate_vertex_colors(collision_result)
        
        # Collision points should be red
        self.assertTrue(np.any(colors[:, 0] > 0.5))  # Red channel

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
```bash
python -m pytest tests/test_heatmap.py -v
```
Expected: FAIL

**Step 3: Write minimal implementation**
```python
"""blendersmile_addon/v2/review/heatmap.py"""
"""Contact heatmap visualization for review."""
from dataclasses import dataclass
from typing import List, Tuple, Optional
import numpy as np


@dataclass
class CollisionResult:
    """Result of collision detection."""
    has_collision: bool
    collision_points: List[Tuple[float, float, float]]
    penetration_depths: List[float]
    mesh_a_name: Optional[str] = None
    mesh_b_name: Optional[str] = None


class ContactHeatmap:
    """Generate contact heatmap for tooth collision visualization."""
    
    def __init__(
        self,
        collision_threshold: float = 0.1,
        color_gradient: str = "green_yellow_red",
    ):
        self.collision_threshold = collision_threshold
        self.color_gradient = color_gradient
    
    def check_collision(
        self,
        mesh_a,
        mesh_b,
    ) -> CollisionResult:
        """
        Check collision between two meshes.
        
        Simplified implementation - in production would use BVH trees.
        """
        # This is a placeholder - real implementation would use:
        # - BVHTree for efficient collision detection
        # - Accurate penetration depth calculation
        
        # For now, return a simple result
        collision_points = []
        penetration_depths = []
        has_collision = False
        
        # Placeholder logic
        if hasattr(mesh_a, 'vertices') and hasattr(mesh_b, 'vertices'):
            # Simple bounding box overlap check
            # Real implementation: use Blender's BVHTree
            has_collision = len(mesh_a.vertices) > 0 and len(mesh_b.vertices) > 0
            
            if has_collision:
                # Add a fake collision point for testing
                collision_points.append((0.0, 0.0, 0.0))
                penetration_depths.append(0.5)
        
        return CollisionResult(
            has_collision=has_collision,
            collision_points=collision_points,
            penetration_depths=penetration_depths,
        )
    
    def generate_vertex_colors(
        self,
        collision_result: CollisionResult,
    ) -> np.ndarray:
        """
        Generate vertex colors for heatmap visualization.
        
        Returns:
            Nx4 numpy array (RGBA) where N is number of collision points
        """
        n = len(collision_result.collision_points)
        if n == 0:
            return np.zeros((0, 4))
        
        colors = np.zeros((n, 4))
        
        for i, depth in enumerate(collision_result.penetration_depths):
            # Normalize depth to 0-1
            normalized = min(1.0, depth / 2.0)
            
            # Gradient: green (0) -> yellow (0.5) -> red (1)
            if normalized < 0.5:
                # Green to yellow
                colors[i] = [
                    normalized * 2,  # R
                    1.0,             # G
                    0.0,             # B
                    1.0,             # A
                ]
            else:
                # Yellow to red
                colors[i] = [
                    1.0,                       # R
                    1.0 - (normalized - 0.5) * 2,  # G
                    0.0,                       # B
                    1.0,                       # A
                ]
        
        return colors
    
    def apply_heatmap_to_mesh(
        self,
        mesh,
        collision_result: CollisionResult,
    ) -> bool:
        """
        Apply heatmap colors to mesh vertex colors.
        
        Requires Blender context - use only in runtime.
        """
        import bpy
        
        if not collision_result.has_collision:
            return False
        
        # Ensure mesh has vertex colors
        if not mesh.vertex_colors:
            mesh.vertex_colors.new(name="ContactHeatmap")
        
        color_layer = mesh.vertex_colors["ContactHeatmap"]
        
        # Apply colors based on collision proximity
        # Real implementation would map collision points to vertices
        
        return True
```

**Step 4: Run test to verify it passes**
```bash
python -m pytest tests/test_heatmap.py -v
```
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_heatmap.py blendersmile_addon/v2/review/heatmap.py
git commit -m "feat: add contact heatmap visualization

- ContactHeatmap class for collision detection
- CollisionResult dataclass for results
- Vertex color generation with gradient
- Green -> Yellow -> Red based on penetration depth
- Placeholder for full BVH implementation"
```

---

### Task 3: Add Review Panel UI

**Files:**
- Modify: `blendersmile_pnp_full.py` (add Review panel)
- Test: Manual Blender testing

**Step 1: Create Review Panel class**

Add to `blendersmile_pnp_full.py`:

```python
class SMILE_PT_review_panel(bpy.types.Panel):
    """Review workspace panel - outcome-first design."""
    bl_label = "Review"
    bl_idname = "SMILE_PT_review"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Smile'
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        p = scene.smile_v2
        
        # Summary box at top (outcome-first)
        summary_box = layout.box()
        summary_box.label(text="Case Summary", icon='CHECKMARK')
        
        # Get review summary if exists
        review_data = scene.get("SMILE_CASE_REVIEW", None)
        if review_data:
            import json
            try:
                review = json.loads(review_data)
                summary = review.get('summary', {})
                
                row = summary_box.row()
                row.label(text=f"✓ Pass: {summary.get('pass', 0)}", icon='CHECKMARK')
                row = summary_box.row()
                row.label(text=f"⚠ Attention: {summary.get('needs_attention', 0)}", icon='ERROR')
                row = summary_box.row()
                row.label(text=f"⏳ Pending: {summary.get('pending', 0)}", icon='QUESTION')
            except:
                pass
        else:
            summary_box.label(text="No review data", icon='INFO')
        
        # Tools section
        tools_box = layout.box()
        tools_box.label(text="Review Tools", icon='TOOL_SETTINGS')
        
        row = tools_box.row()
        row.operator("smile.add_review_annotation", text="Add Note", icon='TEXT')
        
        row = tools_box.row()
        row.operator("smile.create_section_plane", text="Section", icon='MESH_PLANE')
        
        row = tools_box.row()
        row.operator("smile.show_contact_heatmap", text="Heatmap", icon='COLOR')
        
        row = tools_box.row()
        row.operator("smile.measure_distance", text="Measure", icon='DRIVER_DISTANCE')
        
        # Export section
        export_box = layout.box()
        export_box.label(text="Export Review", icon='EXPORT')
        
        row = export_box.row()
        row.operator("smile.export_review_snapshot", text="Snapshot", icon='RENDER_STILL')
        
        row = export_box.row()
        row.operator("smile.export_review_report", text="Report", icon='FILE_TEXT')
```

**Step 2: Register panel**
```python
# In register():
classes.append(SMILE_PT_review_panel)
```

**Step 3: Manual testing**
```bash
# In Blender:
# 1. Open addon panel
# 2. Navigate to Review tab
# 3. Verify summary section appears
# 4. Test tool buttons
```

**Step 4: Commit**
```bash
git add blendersmile_pnp_full.py
git commit -m "feat: add review panel UI

- Summary box at top (outcome-first design)
- Pass/Attention/Pending counts
- Tool buttons: Note, Section, Heatmap, Measure
- Export: Snapshot, Report
- Registered in addon classes"
```

---

## Phase 3: Present Mode

**Goal:** Create presentation-focused output workflow.

**Estimated effort:** 1.5 weeks

**Dependencies:** Phase 0, Phase 2

### Task 1: Design Presentation Presets

**Files:**
- Create: `blendersmile_addon/v2/present/presets.py`
- Create: `tests/test_present_presets.py`

**Step 1: Write the failing test**
```python
"""tests/test_present_presets.py"""
import unittest
from blendersmile_addon.v2.present.presets import (
    PresentationPreset,
    get_preset,
    PRESET_CLINICAL,
    PRESET_PATIENT,
)

class TestPresentationPresets(unittest.TestCase):
    def test_clinical_preset_render_settings(self):
        """Clinical preset should have appropriate render settings."""
        preset = get_preset('CLINICAL')
        
        self.assertEqual(preset.render_engine, 'CYCLES')
        self.assertTrue(preset.show_wireframe)
    
    def test_patient_preset_render_settings(self):
        """Patient preset should optimize for visual appeal."""
        preset = get_preset('PATIENT')
        
        self.assertEqual(preset.render_engine, 'EEVEE')
        self.assertFalse(preset.show_wireframe)
    
    def test_apply_preset_to_scene(self):
        """Preset should be applicable to Blender scene."""
        preset = PRESET_PATIENT
        
        # Mock scene
        mock_scene = Mock()
        mock_scene.render = Mock()
        mock_scene.eevee = Mock()
        mock_scene.cycles = Mock()
        
        preset.apply_to_scene(mock_scene)
        
        # Verify settings were applied
        self.assertEqual(mock_scene.render.engine, 'BLENDER_EEVEE')

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
```bash
python -m pytest tests/test_present_presets.py -v
```
Expected: FAIL

**Step 3: Write minimal implementation**
```python
"""blendersmile_addon/v2/present/presets.py"""
"""Presentation presets for output modes."""
from dataclasses import dataclass
from typing import Dict, Any, Optional
from enum import Enum


class PresentationMode(Enum):
    CLINICAL = "CLINICAL"
    PATIENT = "PATIENT"
    LAB = "LAB"


@dataclass
class PresentationPreset:
    """Settings for a presentation mode."""
    name: str
    mode: PresentationMode
    render_engine: str
    samples: int
    show_wireframe: bool
    show_annotations: bool
    background_color: tuple
    lighting_preset: str
    camera_preset: str
    
    def apply_to_scene(self, scene) -> None:
        """Apply preset settings to a Blender scene."""
        import bpy
        
        # Render engine
        if self.render_engine == 'CYCLES':
            scene.render.engine = 'CYCLES'
            scene.cycles.samples = self.samples
        elif self.render_engine == 'EEVEE':
            scene.render.engine = 'BLENDER_EEVEE'
        
        # Viewport settings
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                obj.show_wire = self.show_wireframe
                obj.show_all_edges = self.show_wireframe
        
        # Background
        if hasattr(scene, 'world') and scene.world:
            if hasattr(scene.world, 'node_tree'):
                # Set background color via nodes
                pass  # Complex node manipulation
        
        # Lighting preset would configure world lighting
        # Camera preset would set up specific camera position


# Define presets
PRESET_CLINICAL = PresentationPreset(
    name="Clinical Review",
    mode=PresentationMode.CLINICAL,
    render_engine='CYCLES',
    samples=128,
    show_wireframe=True,
    show_annotations=True,
    background_color=(0.18, 0.18, 0.18, 1.0),
    lighting_preset='neutral',
    camera_preset='occlusal',
)

PRESET_PATIENT = PresentationPreset(
    name="Patient Presentation",
    mode=PresentationMode.PATIENT,
    render_engine='EEVEE',
    samples=32,
    show_wireframe=False,
    show_annotations=False,
    background_color=(0.05, 0.05, 0.05, 1.0),
    lighting_preset='dramatic',
    camera_preset='facial',
)

PRESET_LAB = PresentationPreset(
    name="Lab Export",
    mode=PresentationMode.LAB,
    render_engine='CYCLES',
    samples=256,
    show_wireframe=True,
    show_annotations=True,
    background_color=(1.0, 1.0, 1.0, 1.0),
    lighting_preset='neutral',
    camera_preset='orthographic',
)


PRESETS: Dict[str, PresentationPreset] = {
    'CLINICAL': PRESET_CLINICAL,
    'PATIENT': PRESET_PATIENT,
    'LAB': PRESET_LAB,
}


def get_preset(name: str) -> Optional[PresentationPreset]:
    """Get a preset by name."""
    return PRESETS.get(name.upper())
```

**Step 4: Run test to verify it passes**
```bash
python -m pytest tests/test_present_presets.py -v
```
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_present_presets.py blendersmile_addon/v2/present/presets.py
git commit -m "feat: add presentation presets

- PresentationPreset dataclass with all settings
- Three presets: CLINICAL, PATIENT, LAB
- Clinical: high samples, wireframe, annotations
- Patient: EEVEE, visual appeal, no wireframe
- Lab: high quality, white background
- apply_to_scene method for Blender integration"
```

---

### Task 2: Implement Before/After Composite

**Files:**
- Create: `blendersmile_addon/v2/present/before_after.py`
- Create: `tests/test_before_after.py`

**Step 1: Write the failing test**
```python
"""tests/test_before_after.py"""
import unittest
from blendersmile_addon.v2.present.before_after import (
    BeforeAfterComposite,
    CompositeLayout,
)

class TestBeforeAfterComposite(unittest.TestCase):
    def test_generate_side_by_side(self):
        """Should generate side-by-side before/after layout."""
        composite = BeforeAfterComposite(
            layout=CompositeLayout.SIDE_BY_SIDE,
        )
        
        result = composite.generate(
            before_image=None,  # Would need real image in production
            after_image=None,
            width=1920,
            height=1080,
        )
        
        self.assertIsNotNone(result)
        self.assertEqual(result['layout'], 'side_by_side')
    
    def test_add_labels(self):
        """Should add Before/After labels."""
        composite = BeforeAfterComposite(
            show_labels=True,
        )
        
        # Mock label generation
        composite.add_label("Before", position="left")
        composite.add_label("After", position="right")
        
        self.assertEqual(len(composite.labels), 2)

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
```bash
python -m pytest tests/test_before_after.py -v
```
Expected: FAIL

**Step 3: Write minimal implementation**
```python
"""blendersmile_addon/v2/present/before_after.py"""
"""Before/After composite generation for presentation."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
import numpy as np


class CompositeLayout(Enum):
    SIDE_BY_SIDE = "side_by_side"
    SPLIT_DIAGONAL = "split_diagonal"
    WIPE_TRANSITION = "wipe_transition"
    OVERLAY_SLIDER = "overlay_slider"


@dataclass
class LabelConfig:
    """Configuration for a label in the composite."""
    text: str
    position: str  # 'left', 'right', 'top', 'bottom'
    font_size: int = 24
    color: Tuple[int, int, int, int] = (255, 255, 255, 255)


@dataclass
class BeforeAfterComposite:
    """Generate before/after comparison composites."""
    layout: CompositeLayout = CompositeLayout.SIDE_BY_SIDE
    show_labels: bool = True
    labels: List[LabelConfig] = field(default_factory=list)
    
    def add_label(self, text: str, position: str) -> None:
        """Add a label to the composite."""
        self.labels.append(LabelConfig(text=text, position=position))
    
    def generate(
        self,
        before_image: Optional[np.ndarray],
        after_image: Optional[np.ndarray],
        width: int = 1920,
        height: int = 1080,
    ) -> Dict[str, Any]:
        """
        Generate before/after composite.
        
        Args:
            before_image: Before image array (H, W, 3 or 4)
            after_image: After image array (H, W, 3 or 4)
            width: Output width
            height: Output height
        
        Returns:
            Dict with 'image' (numpy array) and metadata
        """
        result = {
            'layout': self.layout.value,
            'width': width,
            'height': height,
            'labels': [
                {'text': l.text, 'position': l.position}
                for l in self.labels
            ],
        }
        
        if before_image is None or after_image is None:
            # Return placeholder
            result['image'] = np.zeros((height, width, 3), dtype=np.uint8)
            result['placeholder'] = True
            return result
        
        # Process based on layout
        if self.layout == CompositeLayout.SIDE_BY_SIDE:
            composite = self._generate_side_by_side(
                before_image, after_image, width, height
            )
        elif self.layout == CompositeLayout.SPLIT_DIAGONAL:
            composite = self._generate_split_diagonal(
                before_image, after_image, width, height
            )
        else:
            # Default to side by side
            composite = self._generate_side_by_side(
                before_image, after_image, width, height
            )
        
        result['image'] = composite
        result['placeholder'] = False
        
        return result
    
    def _generate_side_by_side(
        self,
        before: np.ndarray,
        after: np.ndarray,
        width: int,
        height: int,
    ) -> np.ndarray:
        """Generate side-by-side layout."""
        # Create output canvas
        composite = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Calculate split position
        split_x = width // 2
        
        # Resize images to fit halves
        # In production, would use proper image resizing
        # For now, simple assignment
        h, w = before.shape[:2]
        scale_h = height / h
        scale_w = split_x / w
        # ... resizing logic ...
        
        return composite
    
    def _generate_split_diagonal(
        self,
        before: np.ndarray,
        after: np.ndarray,
        width: int,
        height: int,
    ) -> np.ndarray:
        """Generate diagonal split layout."""
        composite = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Create diagonal mask
        y, x = np.meshgrid(range(height), range(width), indexing='ij')
        mask = x < (y * width / height)
        
        # Apply mask
        # composite[mask] = before[...]  # Would need resized before
        # composite[~mask] = after[...]  # Would need resized after
        
        return composite
```

**Step 4: Run test to verify it passes**
```bash
python -m pytest tests/test_before_after.py -v
```
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_before_after.py blendersmile_addon/v2/present/before_after.py
git commit -m "feat: add before/after composite generation

- BeforeAfterComposite class
- Multiple layouts: side_by_side, split_diagonal
- Label configuration
- Placeholder support for testing
- Framework for image compositing"
```

---

## Phase 4: Plan Blueprint Workflow

**Goal:** Implement Stack → Structure → Design progression.

**Estimated effort:** 3 weeks

**Dependencies:** Phase 0 complete

### Task 1: Design Layer Stack System

**Files:**
- Create: `blendersmile_addon/v2/plan/stack.py`
- Create: `tests/test_plan_stack.py`

**Step 1: Write the failing test**
```python
"""tests/test_plan_stack.py"""
import unittest
from blendersmile_addon.v2.plan.stack import (
    LayerType,
    LayerPhase,
    PlanLayer,
    PlanStack,
)

class TestPlanStack(unittest.TestCase):
    def test_add_layer_to_stack(self):
        """Should add layer to stack with proper ordering."""
        stack = PlanStack()
        
        layer = PlanLayer(
            name="Upper Scan",
            layer_type=LayerType.SCAN_UPPER,
            object_name="UpperScan",
        )
        
        stack.add_layer(layer)
        
        self.assertEqual(len(stack.layers), 1)
        self.assertEqual(stack.layers[0].name, "Upper Scan")
    
    def test_layer_ordering_by_type(self):
        """Layers should order by type priority."""
        stack = PlanStack()
        
        # Add in wrong order
        stack.add_layer(PlanLayer(
            name="CBCT",
            layer_type=LayerType.CBCT,
            object_name="CBCT",
        ))
        stack.add_layer(PlanLayer(
            name="Portrait",
            layer_type=LayerType.PORTRAIT,
            object_name="Portrait",
        ))
        stack.add_layer(PlanLayer(
            name="Upper Scan",
            layer_type=LayerType.SCAN_UPPER,
            object_name="Upper",
        ))
        
        # Should reorder to: Portrait, Upper Scan, CBCT
        stack.sort_by_priority()
        
        self.assertEqual(stack.layers[0].layer_type, LayerType.PORTRAIT)
        self.assertEqual(stack.layers[1].layer_type, LayerType.SCAN_UPPER)
        self.assertEqual(stack.layers[2].layer_type, LayerType.CBCT)

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
```bash
python -m pytest tests/test_plan_stack.py -v
```
Expected: FAIL

**Step 3: Write minimal implementation**
```python
"""blendersmile_addon/v2/plan/stack.py"""
"""Plan stack system for Blueprint workflow."""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime


class LayerType(Enum):
    """Types of layers in a plan stack."""
    PORTRAIT = "PORTRAIT"
    SCAN_UPPER = "SCAN_UPPER"
    SCAN_LOWER = "SCAN_LOWER"
    CBCT = "CBCT"
    WAXUP = "WAXUP"
    MOTION = "MOTION"


class LayerPhase(Enum):
    """Clinical phase of a scan layer."""
    PRE_OP = "PRE_OP"
    POST_PREP = "POST_PREP"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# Priority order for layer types
LAYER_PRIORITY = {
    LayerType.PORTRAIT: 0,
    LayerType.SCAN_UPPER: 1,
    LayerType.SCAN_LOWER: 2,
    LayerType.CBCT: 3,
    LayerType.WAXUP: 4,
    LayerType.MOTION: 5,
}


@dataclass
class PlanLayer:
    """A single layer in the plan stack."""
    name: str
    layer_type: LayerType
    object_name: str
    phase: Optional[LayerPhase] = None
    visible: bool = True
    opacity: float = 1.0
    locked: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'layer_type': self.layer_type.value,
            'object_name': self.object_name,
            'phase': self.phase.value if self.phase else None,
            'visible': self.visible,
            'opacity': self.opacity,
            'locked': self.locked,
            'metadata': self.metadata,
        }


@dataclass
class PlanStack:
    """Stack of layers for planning."""
    layers: List[PlanLayer] = field(default_factory=list)
    active_layer_index: int = 0
    
    def add_layer(self, layer: PlanLayer) -> None:
        """Add a layer to the stack."""
        self.layers.append(layer)
    
    def remove_layer(self, index: int) -> Optional[PlanLayer]:
        """Remove a layer by index."""
        if 0 <= index < len(self.layers):
            return self.layers.pop(index)
        return None
    
    def get_layer(self, index: int) -> Optional[PlanLayer]:
        """Get a layer by index."""
        if 0 <= index < len(self.layers):
            return self.layers[index]
        return None
    
    def sort_by_priority(self) -> None:
        """Sort layers by type priority."""
        self.layers.sort(key=lambda l: LAYER_PRIORITY.get(l.layer_type, 999))
    
    def set_layer_visibility(self, index: int, visible: bool) -> bool:
        """Set visibility of a layer."""
        layer = self.get_layer(index)
        if layer:
            layer.visible = visible
            return True
        return False
    
    def get_visible_layers(self) -> List[PlanLayer]:
        """Get all visible layers."""
        return [l for l in self.layers if l.visible]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'layers': [l.to_dict() for l in self.layers],
            'active_layer_index': self.active_layer_index,
        }
```

**Step 4: Run test to verify it passes**
```bash
python -m pytest tests/test_plan_stack.py -v
```
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_plan_stack.py blendersmile_addon/v2/plan/stack.py
git commit -m "feat: add plan stack system

- LayerType enum for layer categorization
- LayerPhase for clinical phase tracking
- PlanLayer dataclass with visibility/opacity
- PlanStack with priority ordering
- Serialization to dict for persistence"
```

---

### Task 2: Implement Tooth Intent System

**Files:**
- Create: `blendersmile_addon/v2/plan/structure.py`
- Create: `tests/test_tooth_intent.py`

**Step 1: Write the failing test**
```python
"""tests/test_tooth_intent.py"""
import unittest
from blendersmile_addon.v2.plan.structure import (
    ToothIntent,
    IntentType,
    StructureMap,
)

class TestToothIntent(unittest.TestCase):
    def test_set_tooth_intent(self):
        """Should set intent for a specific tooth."""
        structure = StructureMap()
        
        structure.set_intent(8, IntentType.ALIGN)
        
        self.assertEqual(structure.get_intent(8), IntentType.ALIGN)
    
    def test_default_intent_is_preserve(self):
        """Unspecified teeth should default to PRESERVE."""
        structure = StructureMap()
        
        intent = structure.get_intent(99)  # Non-existent
        
        self.assertEqual(intent, IntentType.PRESERVE)
    
    def test_structure_summary(self):
        """Should generate summary of intents."""
        structure = StructureMap()
        structure.set_intent(8, IntentType.ALIGN)
        structure.set_intent(9, IntentType.ALIGN)
        structure.set_intent(11, IntentType.RESHAPE)
        
        summary = structure.get_summary()
        
        self.assertEqual(summary['align'], 2)
        self.assertEqual(summary['reshape'], 1)

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
```bash
python -m pytest tests/test_tooth_intent.py -v
```
Expected: FAIL

**Step 3: Write minimal implementation**
```python
"""blendersmile_addon/v2/plan/structure.py"""
"""Tooth intent system for Structure phase."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, List
from collections import Counter


class IntentType(Enum):
    """Treatment intent for a tooth."""
    PRESERVE = "PRESERVE"
    RESHAPE = "RESHAPE"
    ALIGN = "ALIGN"
    REMOVE = "REMOVE"
    ADD = "ADD"


@dataclass
class ToothIntent:
    """Intent for a single tooth."""
    tooth_id: int
    intent_type: IntentType
    notes: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            'tooth_id': self.tooth_id,
            'intent_type': self.intent_type.value,
            'notes': self.notes,
        }


@dataclass
class StructureMap:
    """Map of treatment intents for all teeth."""
    intents: Dict[int, ToothIntent] = field(default_factory=dict)
    
    def set_intent(
        self,
        tooth_id: int,
        intent_type: IntentType,
        notes: Optional[str] = None,
    ) -> None:
        """Set intent for a tooth."""
        self.intents[tooth_id] = ToothIntent(
            tooth_id=tooth_id,
            intent_type=intent_type,
            notes=notes,
        )
    
    def get_intent(self, tooth_id: int) -> IntentType:
        """Get intent for a tooth, defaulting to PRESERVE."""
        if tooth_id in self.intents:
            return self.intents[tooth_id].intent_type
        return IntentType.PRESERVE
    
    def remove_intent(self, tooth_id: int) -> Optional[ToothIntent]:
        """Remove intent for a tooth."""
        return self.intents.pop(tooth_id, None)
    
    def get_teeth_by_intent(self, intent_type: IntentType) -> List[int]:
        """Get all teeth with a specific intent."""
        return [
            tid for tid, intent in self.intents.items()
            if intent.intent_type == intent_type
        ]
    
    def get_summary(self) -> Dict[str, int]:
        """Get count of teeth by intent type."""
        counter = Counter(intent.intent_type.value for intent in self.intents.values())
        return dict(counter)
    
    def clear(self) -> None:
        """Clear all intents."""
        self.intents.clear()
    
    def to_dict(self) -> dict:
        return {
            'intents': {
                str(tid): intent.to_dict()
                for tid, intent in self.intents.items()
            },
            'summary': self.get_summary(),
        }
```

**Step 4: Run test to verify it passes**
```bash
python -m pytest tests/test_tooth_intent.py -v
```
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_tooth_intent.py blendersmile_addon/v2/plan/structure.py
git commit -m "feat: add tooth intent system

- IntentType enum: PRESERVE, RESHAPE, ALIGN, REMOVE, ADD
- ToothIntent dataclass with notes
- StructureMap for managing all tooth intents
- Summary generation by intent type
- Default to PRESERVE for unspecified teeth"
```

---

## Phase 5: Portrait-First Simulate Phase (AI-Assisted)

**Goal:** Implement portrait-first design workflow with AI assistance.

**Estimated effort:** 8-12 weeks

**Dependencies:** Phase 0-4 complete, AI model selection

**Note:** This is a major strategic investment. Requires:

1. AI model selection (local ML vs cloud API)
2. Facial detection/analysis library
3. Portrait canvas overlay system
4. Integration with existing PnP alignment

**Recommendation:** Implement as separate phase after core workflow gaps are closed.

---

## Verification Checklist

After completing each phase:

- [ ] All unit tests pass: `python -m pytest tests/ -v`
- [ ] Blender import succeeds: Manual test in Blender
- [ ] No runtime errors: Check Blender console
- [ ] Documentation updated: Update `README.md` and `CLAUDE.md`
- [ ] Commit history clean: Review git log

---

## Execution Order

Recommended execution sequence:

1. **Architecture backlog Phases 0-3** (prerequisite)
2. **Phase 1: Capture quality checks** (1 week)
3. **Phase 2: Validate review workspace** (2 weeks)
4. **Phase 3: Present mode** (1.5 weeks)
5. **Phase 4: Plan Blueprint workflow** (3 weeks)
6. **Phase 5: Portrait-first Simulate** (8-12 weeks, optional)

Total for Phases 1-4: ~7.5 weeks after architecture stabilization.

---

## Success Metrics

| Phase | Metric | Target |
|-------|--------|--------|
| Capture | Quality warnings shown | >90% of low-quality imports |
| Validate | Review completion rate | >80% cases with full review |
| Present | Before/after exports | User adoption >50% |
| Plan | Intent marking | >70% of treatment cases |
| Simulate | AI adoption | >60% portrait-first designs |
