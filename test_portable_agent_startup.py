"""Exercise agent imports with the isolated path used by embedded Python."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PortableAgentStartupTests(unittest.TestCase):
    def test_imports_from_isolated_runtime_outside_application_directory(self):
        agent = Path(__file__).resolve().with_name("cloud_agent.py")
        # Import without running checks, contacting services or updating Git.
        with tempfile.TemporaryDirectory() as other_directory:
            result = subprocess.run(
                [sys.executable, "-I", "-c",
                 "import runpy, sys; runpy.run_path(sys.argv[1], run_name='agent_import_test')",
                 str(agent)],
                cwd=other_directory, capture_output=True, text=True, timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
