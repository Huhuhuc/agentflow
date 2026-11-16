import pytest

from evaluation.retrieval_abstention import calibrate_threshold, evaluate_threshold


def test_threshold_calibrates_on_dev_and_reports_false_answer_and_abstention():
    dev = [
        {"answerable": True, "top_score": 0.9, "top1_correct": True},
        {"answerable": True, "top_score": 0.8, "top1_correct": False},
        {"answerable": False, "top_score": 0.2, "top1_correct": False},
        {"answerable": False, "top_score": 0.1, "top1_correct": False},
    ]
    calibration = calibrate_threshold(dev)
    test = [
        {"answerable": True, "top_score": 0.95, "top1_correct": True},
        {"answerable": True, "top_score": 0.3, "top1_correct": False},
        {"answerable": False, "top_score": 0.92, "top1_correct": False},
        {"answerable": False, "top_score": 0.15, "top1_correct": False},
    ]

    metrics = evaluate_threshold(test, calibration["threshold"])
    assert metrics["correct_answers"] == 1
    assert metrics["false_answers"] == 1
    assert metrics["correct_abstentions"] == 1
    assert metrics["abstained_answerable"] == 1
    assert metrics["answer_precision"] == pytest.approx(0.5)
    assert metrics["false_answer_rate"] == pytest.approx(0.5)


def test_threshold_requires_both_classes_and_labels():
    with pytest.raises(ValueError, match="answerable and unanswerable"):
        evaluate_threshold([{"answerable": True, "top_score": 1, "top1_correct": True}], 0)
    with pytest.raises(ValueError, match="labels"):
        calibrate_threshold([{"answerable": True, "top_score": 1}])
