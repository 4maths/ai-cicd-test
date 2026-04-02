"""
pr_analyzer.py — Module 1: AI-powered Pull Request Reviewer.

Lay code diff tu GitHub PR, gui len LLM de phan tich,
post ket qua vao comment cua PR.

Bien moi truong can thiet:
    GITHUB_TOKEN   : GitHub Actions token (tu dong co san)
    GEMINI_API_KEY : Gemini API key
    GROQ_API_KEY   : Groq API key (fallback)
    REPO           : Ten repository dang 'owner/repo'
    PR_NUMBER      : So thu tu cua Pull Request
"""

from __future__ import annotations

import os
import sys
import logging
from github import Github, GithubException
from ai_engine import call_llm, parse_json_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MAX_DIFF_CHARS = 4000  # Gioi han ky tu diff gui len LLM


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def get_pr_diff(repo_name: str, pr_number: int, token: str) -> str:
    """
    Lay noi dung diff cua Pull Request tu GitHub API.

    Args:
        repo_name: Ten repo dang 'owner/repo'.
        pr_number: So thu tu PR.
        token: GitHub personal access token.

    Returns:
        Chuoi diff (toi da MAX_DIFF_CHARS ky tu), hoac chuoi rong neu loi.
    """
    try:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        diff_parts: list[str] = []
        for f in pr.get_files():
            if f.patch:
                diff_parts.append(f"### {f.filename}\n{f.patch}")

        full_diff = "\n\n".join(diff_parts)
        if len(full_diff) > MAX_DIFF_CHARS:
            logger.info("Diff qua dai, cat xuong %d ky tu.", MAX_DIFF_CHARS)
            return full_diff[:MAX_DIFF_CHARS] + "\n...[diff bi cat bot]"
        return full_diff

    except GithubException as exc:
        logger.error("Loi khi lay PR diff: %s", exc)
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
        logger.info("Da post comment len PR #%d thanh cong.", pr_number)
        return True
    except GithubException as exc:
        logger.error("Loi khi post comment: %s", exc)
        return False


# ---------------------------------------------------------------------------
# AI analysis
# ---------------------------------------------------------------------------

def build_review_prompt(diff: str) -> str:
    """
    Xay dung prompt gui len LLM de review code diff.

    Args:
        diff: Noi dung diff cua PR.

    Returns:
        Chuoi prompt hoan chinh.
    """
    return f"""Ban la mot senior DevOps engineer va code reviewer co kinh nghiem.
Nhiem vu: Phan tich code diff duoi day va tra ve ket qua CHINH XAC theo dinh dang JSON.

Code diff:
{diff}

Yeu cau phan tich:
1. Tim bug hoac logic error tiem an
2. Danh gia rui ro bao mat (security risk)
3. Kiem tra chat luong code (naming, structure, duplication)
4. De xuat cai tien cu the

Tra ve DUNG FORMAT JSON sau (khong giai thich them, khong markdown):
{{
  "summary": "Tom tat ngan gon thay doi trong PR (1-2 cau)",
  "risk_level": "LOW | MEDIUM | HIGH",
  "bugs": ["Mo ta bug 1", "Mo ta bug 2"],
  "security_issues": ["Rui ro bao mat 1"],
  "code_quality": ["Nhan xet chat luong 1"],
  "suggestions": ["Goi y cai thien 1", "Goi y 2"],
  "approved": true
}}

Chi tra ve JSON, khong co bat ky van ban nao khac.
"""


def format_review_comment(analysis: dict, pr_number: int) -> str:
    """
    Dinh dang ket qua phan tich thanh Markdown comment dep.

    Args:
        analysis: Dict chua ket qua phan tich tu LLM.
        pr_number: So PR de hien thi trong tieu de.

    Returns:
        Chuoi Markdown san sang post len GitHub.
    """
    risk = analysis.get("risk_level", "UNKNOWN")
    risk_icon = {"LOW": "GREEN", "MEDIUM": "YELLOW", "HIGH": "RED"}.get(risk, "GREY")
    approved = analysis.get("approved", False)
    status_line = "APPROVED" if approved else "CHANGES REQUESTED"

    def render_list(items: list, fallback: str = "Khong phat hien van de.") -> str:
        if not items:
            return f"- {fallback}"
        return "\n".join(f"- {item}" for item in items)

    return f"""## AI PR Review — #{pr_number}

**Trang thai:** {status_line}
**Muc do rui ro:** {risk_icon} {risk}

### Tom tat
{analysis.get('summary', 'Khong co tom tat.')}

### Bug / Logic Error
{render_list(analysis.get('bugs', []))}

### Bao mat
{render_list(analysis.get('security_issues', []))}

### Chat luong code
{render_list(analysis.get('code_quality', []))}

### Goi y cai thien
{render_list(analysis.get('suggestions', []))}

---
*Phan tich tu dong boi AI CI/CD Assistant — Gemini 1.5 Flash*
"""


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Chay PR Analyzer: lay diff, phan tich, post comment."""
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("REPO", "")
    pr_number_str = os.getenv("PR_NUMBER", "")

    if not all([token, repo, pr_number_str]):
        logger.error("Thieu bien moi truong: GITHUB_TOKEN, REPO, hoac PR_NUMBER.")
        sys.exit(1)

    try:
        pr_number = int(pr_number_str)
    except ValueError:
        logger.error("PR_NUMBER khong hop le: %s", pr_number_str)
        sys.exit(1)

    logger.info("Bat dau phan tich PR #%d tren %s", pr_number, repo)

    diff = get_pr_diff(repo, pr_number, token)
    if not diff:
        logger.warning("Diff rong, bo qua phan tich.")
        sys.exit(0)

    prompt = build_review_prompt(diff)
    raw_response = call_llm(prompt, max_tokens=1000)

    if not raw_response:
        logger.error("LLM khong tra ve ket qua.")
        sys.exit(1)

    analysis = parse_json_response(raw_response)
    if not analysis:
        logger.error("Khong the parse JSON tu LLM. Raw: %s", raw_response[:300])
        sys.exit(1)

    comment_body = format_review_comment(analysis, pr_number)
    success = post_pr_comment(repo, pr_number, token, comment_body)

    if not success:
        sys.exit(1)

    logger.info("PR Analyzer hoan thanh.")


if __name__ == "__main__":
    main()
