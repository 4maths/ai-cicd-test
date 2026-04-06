"""
log_analyzer.py — Module 2: AI-powered Build Failure Analyzer.

Lay log tu GitHub Actions workflow that bai, gui len LLM de tim root cause,
post ket qua vao comment cua PR lien quan.

Bien moi truong can thiet:
    GITHUB_TOKEN   : GitHub Actions token (tu dong co san)
    GROQ_API_KEY   : Groq API key
    REPO           : Ten repository dang 'owner/repo'
    RUN_ID         : ID cua workflow run that bai
    PR_NUMBER      : So PR lien quan (co the rong)
"""

from __future__ import annotations

import os
import sys
import logging
from github import Github, GithubException
from ai_engine import call_llm, parse_json_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MAX_LOG_CHARS = 3000  # Chi lay 3000 ky tu cuoi cua log (phan quan trong nhat)


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def get_workflow_logs(repo_name: str, run_id: int, token: str) -> str:
    """
    Lay log cua tat ca jobs trong mot workflow run cu the.

    Args:
        repo_name: Ten repo dang 'owner/repo'.
        run_id: ID cua workflow run.
        token: GitHub personal access token.

    Returns:
        Chuoi log gop lai (toi da MAX_LOG_CHARS ky tu cuoi), hoac rong neu loi.
    """
    try:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        run = repo.get_workflow_run(run_id)

        log_parts: list[str] = []
        for job in run.jobs():
            job_header = f"=== JOB: {job.name} | Status: {job.conclusion} ==="
            step_logs: list[str] = []
            for step in job.steps:
                step_logs.append(
                    f"[Step: {step.name} | {step.conclusion}]"
                )
            log_parts.append(job_header + "\n" + "\n".join(step_logs))

        combined = "\n\n".join(log_parts)

        # Chi lay phan cuoi — noi thuong chua loi chinh
        if len(combined) > MAX_LOG_CHARS:
            logger.info("Log qua dai, chi lay %d ky tu cuoi.", MAX_LOG_CHARS)
            return "...[log bi cat phan dau]\n" + combined[-MAX_LOG_CHARS:]
        return combined

    except GithubException as exc:
        logger.error("Loi khi lay workflow logs: %s", exc)
        return ""


def post_pr_comment(repo_name: str, pr_number: int, token: str, body: str) -> bool:
    """
    Post comment len Pull Request tren GitHub.

    Args:
        repo_name: Ten repo dang 'owner/repo'.
        pr_number: So thu tu PR.
        token: GitHub personal access token.
        body: Noi dung comment (Markdown).

    Returns:
        True neu thanh cong, False neu that bai.
    """
    try:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        pr.create_issue_comment(body)
        logger.info("Da post comment len PR #%d.", pr_number)
        return True
    except GithubException as exc:
        logger.error("Loi khi post comment: %s", exc)
        return False


# ---------------------------------------------------------------------------
# AI analysis
# ---------------------------------------------------------------------------

def build_log_prompt(log_content: str) -> str:
    """
    Xay dung prompt gui len LLM de phan tich log CI that bai.

    Args:
        log_content: Noi dung log da duoc lay tu GitHub.

    Returns:
        Chuoi prompt hoan chinh.
    """
    return f"""Ban la mot DevOps engineer giau kinh nghiem trong viec debug CI/CD pipeline.
Nhiem vu: Phan tich log CI that bai duoi day va tim ra nguyen nhan goc re (root cause).

Log CI:
{log_content}

Yeu cau phan tich:
1. Xac dinh chinh xac buoc (step) nao bi loi
2. Giai thich nguyen nhan goc re
3. De xuat cach sua loi cu the va co the thuc hien ngay
4. Goi y cach ngan ngua loi nay tai xay ra

Tra ve DUNG FORMAT JSON sau (khong giai thich them, khong markdown):
{{
  "error_type": "Loai loi: build_error | test_failure | dependency_error | config_error | network_error | other",
  "failed_step": "Ten buoc bi loi cu the",
  "root_cause": "Mo ta nguyen nhan goc re (2-3 cau ro rang)",
  "suggested_fix": "Huong dan sua loi step-by-step",
  "confidence": "HIGH | MEDIUM | LOW",
  "prevention": "Cach ngan ngua loi nay tai xay ra"
}}

Chi tra ve JSON, khong co bat ky van ban nao khac.
"""


def format_log_comment(analysis: dict, run_id: int) -> str:
    """
    Dinh dang ket qua phan tich log thanh Markdown comment.

    Args:
        analysis: Dict chua ket qua phan tich tu LLM.
        run_id: ID workflow run de hien thi trong tieu de.

    Returns:
        Chuoi Markdown san sang post len GitHub.
    """
    confidence = analysis.get("confidence", "UNKNOWN")
    conf_icon = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}.get(confidence, "?")

    return f"""## AI Build Failure Analysis — Run #{run_id}

**Loai loi:** {analysis.get('error_type', 'unknown')}
**Buoc that bai:** `{analysis.get('failed_step', 'Khong xac dinh')}`
**Do tin cay phan tich:** {conf_icon} {confidence}

### Nguyen nhan goc re
{analysis.get('root_cause', 'Khong the xac dinh nguyen nhan.')}

### Huong dan sua loi
{analysis.get('suggested_fix', 'Khong co goi y cu the.')}

### Ngan ngua tai xay ra
{analysis.get('prevention', 'Khong co goi y.')}

---
*Phan tich tu dong boi AI CI/CD Assistant — Groq Llama 3.1*
"""


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Chay Log Analyzer: lay log, phan tich, post comment."""
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("REPO", "")
    run_id_str = os.getenv("RUN_ID", "")
    pr_number_str = os.getenv("PR_NUMBER", "")

    if not all([token, repo, run_id_str]):
        logger.error("Thieu bien moi truong: GITHUB_TOKEN, REPO, hoac RUN_ID.")
        sys.exit(1)

    try:
        run_id = int(run_id_str)
    except ValueError:
        logger.error("RUN_ID khong hop le: %s", run_id_str)
        sys.exit(1)

    pr_number: int | None = None
    if pr_number_str:
        try:
            pr_number = int(pr_number_str)
        except ValueError:
            logger.warning("PR_NUMBER khong hop le, se bo qua post comment: %s", pr_number_str)

    logger.info("Bat dau phan tich log cho run #%d tren %s", run_id, repo)

    log_content = get_workflow_logs(repo, run_id, token)
    if not log_content:
        logger.warning("Log rong, bo qua phan tich.")
        sys.exit(0)

    prompt = build_log_prompt(log_content)
    raw_response = call_llm(prompt, max_tokens=1000)

    if not raw_response:
        logger.error("LLM khong tra ve ket qua.")
        sys.exit(1)

    analysis = parse_json_response(raw_response)
    if not analysis:
        logger.error("Khong the parse JSON tu LLM. Raw: %s", raw_response[:300])
        sys.exit(1)

    comment_body = format_log_comment(analysis, run_id)

    if pr_number:
        post_pr_comment(repo, pr_number, token, comment_body)
    else:
        logger.info("Khong co PR_NUMBER, in ket qua ra stdout:\n%s", comment_body)

    logger.info("Log Analyzer hoan thanh.")


if __name__ == "__main__":
    main()
