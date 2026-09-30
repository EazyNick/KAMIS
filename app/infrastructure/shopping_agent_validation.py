"""Validate UI collector completion with the same policy as the ingestion path."""

import argparse
from collections import Counter
import json
from pathlib import Path

from app.infrastructure.coupang_agent_csv import CoupangAgentCsvParser
from app.infrastructure.naver_agent_csv import NaverAgentCsvParser


def validate_collection(csv_path, manifest, catalog, platform):
    parser = NaverAgentCsvParser() if platform == "naver" else CoupangAgentCsvParser()
    parsed = parser.parse(csv_path, manifest, catalog)
    targets = {}
    for key, offers in parsed.offers_by_key.items():
        targets[":".join(key)] = {
            "comparable_count": sum(offer.is_comparable for offer in offers),
            "excluded_reasons": dict(Counter(
                offer.exclusion_reason or ("sold_out" if not offer.available else "match_rejected")
                for offer in offers if not offer.is_comparable
            )),
        }
    failed = sorted(":".join(key) for key in parsed.failed_keys)
    completed = len(targets) - len(failed)
    status = {
        "status": "success" if not failed else "partial" if completed else "failed",
        "target_count": len(targets), "completed_count": completed,
        "failed_keys": failed, "csv_path": str(csv_path.resolve()),
    }
    return status, {"targets": targets, "invalid_row_count": parsed.invalid_row_count,
                    "errors": list(parsed.errors)}


def main():
    from app.infrastructure.csv_repository import CatalogRepository
    from config.server_config import Settings
    from log import app_logger

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--platform", choices=("naver", "coupang"), required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    run_dir = Path(manifest["run_dir"]).resolve()
    csv_path = Path(manifest["output_csv"]).resolve()
    if not csv_path.is_relative_to(run_dir) or not args.manifest.resolve().is_relative_to(run_dir):
        raise ValueError("Manifest and CSV must be within run_dir")
    settings = Settings.from_env()
    catalog = {(entry.item_code, entry.kind_code): entry
               for entry in CatalogRepository(settings.data_dir, app_logger).entries()}
    status, diagnostics = validate_collection(csv_path, manifest, catalog, args.platform)
    report = run_dir / "validation-report.json"
    temporary = report.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(report)
    app_logger.info("shopping_agent.validation", "Validated collected offers",
                    platform=args.platform, completed_count=status["completed_count"],
                    failed_keys=status["failed_keys"], report_path=report)
    print(json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
