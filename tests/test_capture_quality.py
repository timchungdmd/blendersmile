"""Tests for capture quality checks."""

import unittest
from unittest.mock import Mock


class TestScanQualityChecker(unittest.TestCase):
    def test_detect_low_vertex_count(self):
        from blendersmile_addon.v2.capture.quality_checks import (
            ScanQualityChecker,
            Severity,
        )

        mock_mesh = Mock()
        mock_mesh.vertices = [Mock() for _ in range(10)]

        checker = ScanQualityChecker(min_vertices=100)
        issues = checker.check(mock_mesh)

        self.assertTrue(
            any(
                i.severity == Severity.INFO and "vertex" in i.message.lower()
                for i in issues
            )
        )

    def test_detect_missing_normals(self):
        from blendersmile_addon.v2.capture.quality_checks import (
            ScanQualityChecker,
            Severity,
        )

        mock_mesh = Mock()
        mock_mesh.vertices = [Mock() for _ in range(100)]
        mock_mesh.loop_triangles = [Mock() for _ in range(50)]
        del mock_mesh.vertices[0].normal

        checker = ScanQualityChecker()
        issues = checker.check(mock_mesh)

        self.assertTrue(
            any(
                i.severity == Severity.WARNING and "normal" in i.message.lower()
                for i in issues
            )
        )


class TestPhotoQualityChecker(unittest.TestCase):
    def test_detect_underexposure(self):
        from blendersmile_addon.v2.capture.quality_checks import (
            PhotoQualityChecker,
            Severity,
        )
        import numpy as np

        dark_image = np.zeros((100, 100, 3), dtype=np.uint8) + 30

        checker = PhotoQualityChecker()
        issues = checker.check_brightness(dark_image, min_brightness=0.3)

        self.assertTrue(
            any(
                i.severity == Severity.WARNING and "exposure" in i.message.lower()
                for i in issues
            )
        )

    def test_detect_low_resolution(self):
        from blendersmile_addon.v2.capture.quality_checks import (
            PhotoQualityChecker,
            Severity,
        )
        import numpy as np

        small_image = np.zeros((400, 300, 3), dtype=np.uint8)

        checker = PhotoQualityChecker(min_resolution=(800, 600))
        issues = checker.check_resolution(small_image)

        self.assertTrue(
            any(
                i.severity == Severity.INFO and "resolution" in i.message.lower()
                for i in issues
            )
        )


class TestImportWithQuality(unittest.TestCase):
    def test_format_quality_report(self):
        from blendersmile_addon.v2.capture.quality_checks import QualityIssue, Severity
        from blendersmile_addon.v2.capture.import_with_quality import (
            format_quality_report,
        )

        issues = [
            QualityIssue(Severity.WARNING, "Low vertex count"),
            QualityIssue(Severity.INFO, "Test info", suggestion="Do something"),
        ]

        report = format_quality_report(issues)

        self.assertIn("Quality Issues Detected", report)
        self.assertIn("Low vertex count", report)
        self.assertIn("[WARN]", report)
        self.assertIn("[INFO]", report)

    def test_format_empty_report(self):
        from blendersmile_addon.v2.capture.import_with_quality import (
            format_quality_report,
        )

        report = format_quality_report([])

        self.assertIn("passed", report.lower())


if __name__ == "__main__":
    unittest.main()
