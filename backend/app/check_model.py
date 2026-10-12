"""Local configuration check; --live performs one bounded real Agent evaluation."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from .config import settings


def configuration_errors():
    errors = []
    if not settings.openai_api_key.strip(): errors.append("Missing API key. Fill OPENAI_API_KEY in backend/.env locally.")
    url = urlparse(settings.openai_base_url)
    if url.scheme != "https" or url.hostname != "api.deepseek.com" or url.username or url.password or url.query or url.fragment or url.path.rstrip("/") not in {"", "/v1"}:
        errors.append("For this DeepSeek check, set OPENAI_BASE_URL=https://api.deepseek.com")
    if not settings.openai_model.strip(): errors.append("OPENAI_MODEL is empty.")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send one synthetic task to DeepSeek (uses API credits)")
    args = parser.parse_args()
    errors = configuration_errors()
    if errors:
        for error in errors: print(error)
        return 2
    print("DeepSeek configuration is present; API key is hidden. This alone does not verify authentication.")
    if not args.live: return 0
    from .business_evaluation import evaluate, export_report
    report = evaluate(mode="openai", split="dev", limit=1)
    path = Path(__file__).resolve().parents[1] / "evaluation/reports/deepseek-smoke.json"
    export_report(report, path)
    row = report["rows"][0]
    print(json.dumps({"status": row["status"], "contract_pass": row["contract_pass"], "tokens": row["observed_total_tokens"], "error": row["error"]}, ensure_ascii=True))
    print(f"Report: {path}")
    if row["status"] == "failed":
        print("401: check API key; 402: check API balance; 400/404: check model and parameters; 429: rate limit; timeout/5xx: retry later.")
    return 0 if row["contract_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
