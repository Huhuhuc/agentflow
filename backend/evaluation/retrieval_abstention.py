"""Dev-calibrated abstention metrics for the offline retrieval benchmark."""
import math


def evaluate_threshold(rows, threshold):
    answerable = sum(bool(row["answerable"]) for row in rows)
    unanswerable = len(rows) - answerable
    if not answerable or not unanswerable:
        raise ValueError("Evaluation split must contain answerable and unanswerable queries")

    predicted = [row["top_score"] >= threshold for row in rows]
    correct_answers = sum(
        is_answer and row["answerable"] and row["top1_correct"]
        for row, is_answer in zip(rows, predicted)
    )
    unsupported_answers = sum(
        is_answer and row["answerable"] and not row["top1_correct"]
        for row, is_answer in zip(rows, predicted)
    )
    false_answers = sum(
        is_answer and not row["answerable"]
        for row, is_answer in zip(rows, predicted)
    )
    correct_abstentions = sum(
        not is_answer and not row["answerable"]
        for row, is_answer in zip(rows, predicted)
    )
    abstained_answerable = sum(
        not is_answer and row["answerable"]
        for row, is_answer in zip(rows, predicted)
    )
    answer_count = sum(predicted)
    return {
        "queries": len(rows),
        "answerable_queries": answerable,
        "unanswerable_queries": unanswerable,
        "threshold": threshold,
        "correct_answers": correct_answers,
        "unsupported_answers": unsupported_answers,
        "false_answers": false_answers,
        "correct_abstentions": correct_abstentions,
        "abstained_answerable": abstained_answerable,
        "coverage": answer_count / len(rows),
        "answer_precision": correct_answers / answer_count if answer_count else 0.0,
        "answer_recall": correct_answers / answerable,
        "false_answer_rate": false_answers / unanswerable,
        "false_abstention_rate": abstained_answerable / answerable,
        "balanced_outcome_rate": (correct_answers / answerable + correct_abstentions / unanswerable) / 2,
    }


def calibrate_threshold(dev_rows):
    """Choose a score cutoff on dev only; ties prefer fewer false answers, then higher cutoff."""
    if not dev_rows or any("top_score" not in row or "top1_correct" not in row for row in dev_rows):
        raise ValueError("Dev rows require top_score and top1_correct labels")
    scores = sorted({float(row["top_score"]) for row in dev_rows})
    candidates = [math.nextafter(scores[0], -math.inf), *scores, math.nextafter(scores[-1], math.inf)]
    evaluated = [(evaluate_threshold(dev_rows, threshold), threshold) for threshold in candidates]
    metrics, threshold = max(
        evaluated,
        key=lambda pair: (
            pair[0]["balanced_outcome_rate"],
            -pair[0]["false_answers"],
            pair[1],
        ),
    )
    return {"threshold": threshold, "dev_metrics": metrics, "selection": "max balanced_outcome_rate; ties prefer fewer false answers, then higher threshold"}
