from __future__ import annotations

import logging
import os

from scripts.security_scanner import (
    format_security_comment,
    get_pr,
    get_pr_files,
    has_override_label,
    load_path_config,
    load_rules,
    post_pr_comment,
    scan_text,
    should_scan_file,
)

logger = logging.getLogger(__name__)


def run_security_scan() -> int:
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("REPO", "")
    pr_number_str = os.getenv("PR_NUMBER", "")

    if not all([token, repo, pr_number_str]):
        logger.error("Thiếu biến môi trường: GITHUB_TOKEN, REPO hoặc PR_NUMBER.")
        return 1

    try:
        pr_number = int(pr_number_str)
    except ValueError:
        logger.error("PR_NUMBER không hợp lệ: %s", pr_number_str)
        return 1

    rules = load_rules("config/security_rules.yml")
    path_config = load_path_config("config/security_paths.yml")

    try:
        pr = get_pr(repo, pr_number, token)
    except Exception as exc:
        logger.error("Không thể lấy PR #%d: %s", pr_number, exc)
        return 1

    override = has_override_label(pr)
    logger.info("Override label status: %s", override)

    files_data = get_pr_files(repo, pr_number, token)
    if not files_data:
        logger.warning("Không lấy được file diff từ PR hoặc PR không có patch.")
        return 0

    all_findings: list[dict] = []
    scanned_files = 0
    skipped_files = 0

    for filename, patch_text in files_data:
        if not should_scan_file(filename, path_config):
            skipped_files += 1
            logger.info("SKIPPED by path filter: %s", filename)
            continue

        scanned_files += 1
        logger.info("SCANNING: %s", filename)
        all_findings.extend(scan_text(filename, patch_text, rules))

    logger.info(
        "Security scan summary: scanned_files=%d, skipped_files=%d, findings=%d",
        scanned_files,
        skipped_files,
        len(all_findings),
    )

    comment_body = format_security_comment(all_findings, pr_number, override)
    success = post_pr_comment(repo, pr_number, token, comment_body)

    if not success:
        logger.warning("Không post được security comment, exit gracefully.")
        return 0

    high_findings = [f for f in all_findings if f["severity"] == "HIGH"]

    if high_findings and not override:
        logger.warning("Có HIGH và không override → fail workflow.")
        return 1

    logger.info("Security Scanner hoàn thành.")
    return 0