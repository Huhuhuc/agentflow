import copy
import json
import pytest

from app.business_evaluation import CASES, evaluate, export_report
from app.business_agent import mock_turn
from app.config import settings


def test_fixed_dataset_and_mock_report(tmp_path):
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert len({c["id"] for c in cases}) == len(cases) == 24
    dev = {c["text"] for c in cases if c["split"] == "dev"}
    test = {c["text"] for c in cases if c["split"] == "test"}
    assert len(dev) == len(test) == 12 and dev.isdisjoint(test)
    report = evaluate()
    assert report["metrics"]["cases"] == 12
    assert report["metrics"]["semantic_success_rate"] is None
    assert report["metrics"]["estimated_cost"] is None
    # The three baseline failures were fixed without changing gold labels.
    assert report["metrics"]["contract_pass_rate"] == 1
    export_report(report, tmp_path / "report.json")
    assert all((tmp_path / ("report." + ext)).exists() for ext in ("json", "csv", "md"))


def test_real_mode_requires_configuration(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(ValueError, match="missing"): evaluate("openai")


def test_usage_cost_and_labels_do_not_leak():
    def adapter(messages, snap):
        assert "action" not in snap and "fact" not in snap and "expected_action" not in snap
        response = copy.deepcopy(mock_turn(messages, snap))
        return {**response, "tokens": 30, "attempts": 1, "usage": {"prompt_tokens": 20, "completion_tokens": 10}}
    report = evaluate("openai", limit=1, input_price=1, output_price=2, adapter=adapter)
    row = report["rows"][0]
    assert row["usage_complete"] and row["observed_total_tokens"] == 60
    assert row["estimated_cost"] == pytest.approx(.00008)
    assert row["human_review"]["status"] == "pending"


def test_missing_usage_is_unknown_not_free():
    report = evaluate("openai", limit=1, input_price=1, output_price=2, adapter=mock_turn)
    assert report["metrics"]["estimated_cost"] is None
    assert report["rows"][0]["prompt_tokens"] is None


def test_invalid_price_and_bounds():
    for kwargs in ({"repeats": 6}, {"limit": 0}, {"input_price": 1}, {"input_price": -1, "output_price": 2}):
        with pytest.raises(ValueError): evaluate(**kwargs)


def test_comparison_rejects_unmatched_samples():
    from app.business_evaluation import compare_reports
    report = evaluate(limit=1)
    other = copy.deepcopy(report)
    assert compare_reports(report, other)["metric_deltas"]["contract_pass_rate"] == 0
    other["split"] = "test"
    with pytest.raises(ValueError): compare_reports(report, other)
