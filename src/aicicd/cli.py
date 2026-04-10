from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aicicd",
        description="AI-assisted CI/CD toolkit",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "pr-review",
        help="Run PR review analysis",
        description="Analyze pull request diff and generate AI review output",
    )

    subparsers.add_parser(
        "security-scan",
        help="Run security scanner",
        description="Run rule-based security scan on pull request diff",
    )

    subparsers.add_parser(
        "log-analysis",
        help="Run CI log analysis",
        description="Analyze failed CI workflow logs",
    )

    subparsers.add_parser(
        "deploy-guard",
        help="Run deploy guard checks",
        description="Check service health after deployment",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "pr-review":
        from aicicd.core.pr_review import run_pr_review
        sys.exit(run_pr_review())

    if args.command == "security-scan":
        from aicicd.core.security_scan import run_security_scan
        sys.exit(run_security_scan())

    if args.command == "log-analysis":
        from aicicd.core.log_analysis import run_log_analysis
        sys.exit(run_log_analysis())

    if args.command == "deploy-guard":
        from aicicd.core.deploy_guard import run_deploy_guard
        sys.exit(run_deploy_guard())

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()