"""CI gate: the offline eval suite must pass in full."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_evals", ROOT / "evals" / "run_evals.py")
run_evals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_evals)


def test_all_eval_cases_pass():
    for case, failures in run_evals.run_all():
        assert not failures, f"{case['case_id']} ({case['name']}): {failures}"
