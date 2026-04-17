import os
import tempfile
import unittest
from pathlib import Path

from sonar.props import discover_report_task


class TestSonarReportTaskDiscovery(unittest.TestCase):
    def test_discovers_report_task_under_custom_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base_dir = Path(d)
            workdir = base_dir / ".scannerwork" / "custom"
            workdir.mkdir(parents=True)
            (workdir / "report-task.txt").write_text(
                "ceTaskUrl=http://example/\nserverUrl=http://sonar/\nprojectKey=p\n",
                encoding="utf-8",
            )

            report, tried = discover_report_task(
                base_dir=base_dir,
                props={"sonar.working.directory": ".scannerwork/custom"},
                scanner_metadata_path=base_dir / "not-there.txt",
                scanner_working_directory=base_dir / ".scannerwork",
                temp_dir=None,
            )

            self.assertIsNotNone(report)
            self.assertIn("ceTaskUrl", report or {})
            self.assertTrue(tried)

    def test_discovers_report_task_from_metadata_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base_dir = Path(d)
            target = base_dir / "out" / "report-task.txt"
            target.parent.mkdir(parents=True)
            target.write_text("ceTaskUrl=http://example/\n", encoding="utf-8")

            report, _ = discover_report_task(
                base_dir=base_dir,
                props={"sonar.scanner.metadataFilePath": "out/report-task.txt"},
                scanner_metadata_path=base_dir / "not-there.txt",
                scanner_working_directory=None,
                temp_dir=None,
            )

            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual(report.get("ceTaskUrl"), "http://example/")

    def test_expands_environment_variables_in_paths(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base_dir = Path(d)
            out_dir = base_dir / "expanded"
            out_dir.mkdir(parents=True)
            (out_dir / "report-task.txt").write_text(
                "ceTaskUrl=http://example/\n", encoding="utf-8"
            )

            os.environ["CLEAN_CODE_TEST_OUT"] = str(out_dir)
            try:
                report, _ = discover_report_task(
                    base_dir=base_dir,
                    props={
                        "sonar.scanner.metadataFilePath": "%CLEAN_CODE_TEST_OUT%/report-task.txt"
                    },
                    scanner_metadata_path=None,
                    scanner_working_directory=None,
                    temp_dir=None,
                )
            finally:
                os.environ.pop("CLEAN_CODE_TEST_OUT", None)

            self.assertIsNotNone(report)


if __name__ == "__main__":
    unittest.main()
