import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from jobs.build_period import build_period


def test_streamlit_runtime_reads_published_marts_without_opening_excel(approved_build_inputs, monkeypatch):
    inputs = approved_build_inputs
    build_period(inputs["source"], policy_path=inputs["policy"],
                 rules_path=inputs["rules"], output_root=inputs["output"])
    monkeypatch.setenv("DELFI_MARTS_ROOT", str(inputs["output"]))
    app_path = Path(__file__).parents[1] / "app.py"
    result = AppTest.from_file(str(app_path)).run(timeout=30)
    assert not result.exception
    assert any("DELFI Utilisation Intelligence" in str(element.value) for element in result.title)
