from __future__ import annotations

import logging
import os

from scripts.ai_engine import call_llm, parse_json_response
from scripts.pr_analyzer import (
    build_review_prompt,
    format_review_comment,
    get_pr_diff,
    normalize_analysis,
    post_pr_comment,
)

logger = logging.getLogger(__name__)


def run_pr_review() -> int:
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("REPO", "")
    pr_number_str = os.getenv("PR_NUMBER", "")

    if not all([token, repo, pr_number_str]):
        logger.error("Thiếu biến môi trường: GITHUB_TOKEN, REPO, PR_NUMBER.")
        return 1

    try:
        pr_number = int(pr_number_str)
    except ValueError:
        logger.error("PR_NUMBER không hợp lệ: %s", pr_number_str)
        return 1

    logger.info("Bắt đầu phân tích PR #%d trên %s", pr_number, repo)

    diff = get_pr_diff(repo, pr_number, token)
    if not diff:
        logger.warning("Diff rỗng, bỏ qua phân tích.")
        return 0

    prompt = build_review_prompt(diff)
    raw_response = call_llm(prompt, max_tokens=1000)

    if not raw_response:
        logger.warning("LLM không trả về kết quả. Post notice comment và exit gracefully.")
        notice = f"""## AI PR Review — #{pr_number}
Groq API unavailable.
"""
        post_pr_comment(repo, pr_number, token, notice)
        return 0

    analysis = parse_json_response(raw_response)
    if not analysis:
        logger.warning("Không thể parse JSON từ LLM. Raw: %s", raw_response[:300])
        notice = f"""## AI PR Review — #{pr_number}
Could not parse response.
"""
        post_pr_comment(repo, pr_number, token, notice)
        return 0

    analysis = normalize_analysis(analysis)

    comment_body = format_review_comment(analysis, pr_number)
    success = post_pr_comment(repo, pr_number, token, comment_body)

    if not success:
        logger.warning("Failed to post comment, but exiting gracefully.")
        return 0

    decision = analysis.get("decision", "WARN")
    risk_level = analysis.get("risk_level", "MEDIUM")
    risk_score = analysis.get("risk_score", 0)

    if decision == "BLOCK":
        logger.warning(
            "PR bị AI đánh giá BLOCK. risk_level=%s, risk_score=%s. Fail workflow để chặn merge.",
            risk_level,
            risk_score,
        )
        return 1

    logger.info(
        "PR Analyzer hoàn thành. decision=%s, risk_level=%s, risk_score=%s",
        decision,
        risk_level,
        risk_score,
    )
    return 0