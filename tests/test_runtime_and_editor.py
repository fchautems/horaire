from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from creche_planning.editor import terminate_solver_process  # noqa: E402
from creche_planning.runtime import emit_stage  # noqa: E402


class RuntimeAndEditorTests(unittest.TestCase):
    def test_stage_protocol_contains_index_total_and_budget(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            emit_stage(2, 5, 123.9, "Recherche rapide")
        self.assertEqual(output.getvalue().strip(), "STAGE|2|5|123|Recherche rapide")

    def test_windows_timeout_terminates_the_solver_process_tree(self) -> None:
        process = Mock()
        process.pid = 321
        process.poll.return_value = None
        process.wait.return_value = -1
        with (
            patch("creche_planning.editor.sys.platform", "win32"),
            patch("creche_planning.editor.subprocess.run") as run,
        ):
            terminate_solver_process(process)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "321", "/T", "/F"])
        process.wait.assert_called_once_with(timeout=5)


if __name__ == "__main__":
    unittest.main()
