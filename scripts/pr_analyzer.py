from __future__ import annotations

import logging
import os
import sys

from github import Github, GithubException

from ai_engine import call_llm, parse_json_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MAX_DIFF_CHARS = 4000


def get_pr_diff(repo_name: str, pr_number: int, token: str) -> str:
    """
    Lấy nội dung diff của PR từ GitHub API.

    Arguments:
        repo_name: Tên repo dạng 'owner/repo'
        pr_number: Số Pull Request
        token: GitHub token

    Returns:
        Chuỗi diff, tối đa MAX_DIFF_CHARS, hoặc chuỗi rỗng nếu lỗi
    """
    try:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        diff_parts: list[str] = []
        for changed_file in pr.get_files():
            if changed_file.patch:
                diff_parts.append(f"### {changed_file.filename}\n{changed_file.patch}")

        full_diff = "\n\n".join(diff_parts)
        if len(full_diff) > MAX_DIFF_CHARS:
            logger.info("Diff quá dài, cắt bớt còn %d ký tự.", MAX_DIFF_CHARS)
            return full_diff[:MAX_DIFF_CHARS]

        return full_diff

    except GithubException as exc:
        logger.error("Lỗi khi lấy PR diff: %s", exc)
        return ""


def post_pr_comment(repo_name: str, pr_number: int, token: str, body: str) -> bool:
    """
    Post comment lên Pull Request trên GitHub.

    Arguments:
        repo_name: Tên repo dạng 'owner/repo'
        pr_number: Số Pull Request
        token: GitHub token
        body: Nội dung comment dạng Markdown

    Returns:
        True nếu comment thành công, False nếu thất bại
    """
    try:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        pr.create_issue_comment(body)
        logger.info("Đã post comment lên PR #%d thành công.", pr_number)
        return True
    except GithubException as exc:
        logger.error("Lỗi khi comment lên PR: %s", exc)
        return False


def build_review_prompt(diff: str) -> str:
    """
    Xây dựng prompt để gửi sang LLM.

    Args:
        diff: Nội dung diff của PR

    Returns:
        Prompt hoàn chỉnh
    """
    return f"""Bạn là một senior DevOps engineer và security-minded code reviewer với nhiều năm kinh nghiệm review code trong môi trường production.

Nhiệm vụ:
Hãy phân tích code diff dưới đây như một reviewer thực tế và khó tính.
Chỉ đưa ra nhận xét dựa trên bằng chứng xuất hiện trong diff.
Không tự đoán mò.
Trả về kết quả chính xác theo định dạng JSON.
Không được khen xã giao.
Không được nói chung chung.

Code diff:
{diff}

Mục tiêu review:
1. Tìm bug hoặc logic error có khả năng gây sai chức năng
2. Tìm edge case chưa được xử lý
3. Tìm rủi ro bảo mật hoặc lỗ hổng liên quan đến secret, token, input validation, exception handling
4. Đánh giá chất lượng code: naming, readability, duplication, maintainability, structure
5. Tìm thay đổi có thể gây vỡ backward compatibility, gây tác dụng phụ hoặc làm sai hành vi mong đợi
6. Đưa ra đề xuất sửa cụ thể, ưu tiên đề xuất có thể áp dụng ngay

Các nguyên tắc bắt buộc:
- Chỉ đánh giá dựa trên diff được cung cấp
- Nếu không đủ bằng chứng, hãy giữ mức độ cẩn trọng
- Nếu thay đổi có dấu hiệu sai logic, hãy đưa vào trường "bugs"
- Nếu thay đổi có nguy cơ nhưng chưa chắc chắn, đưa vào "code_quality" hoặc "suggestions", không khẳng định quá mức
- Không viết markdown
- Không thêm bất kỳ văn bản nào ngoài JSON
- Mỗi mục trong list phải là câu ngắn, rõ ràng, cụ thể
- Nếu không có vấn đề nào ở một mục, trả về list rỗng cho mục đó
- Trường "approved" chỉ được đặt là true khi không có bug logic rõ ràng, không có security issue nghiêm trọng và không có vấn đề chất lượng đáng kể

Tiêu chí đánh giá mức độ rủi ro:
- LOW: thay đổi nhỏ, ít khả năng gây lỗi, không có dấu hiệu bug hoặc security issue
- MEDIUM: có một vài điểm đáng nghi, có thể gây lỗi trong một số trường hợp
- HIGH: có dấu hiệu rõ ràng của bug logic, security risk, hoặc thay đổi có thể cản trở hành vi mong đợi

Chú ý các mẫu lỗi thường gặp:
- Tên hàm không đúng hành vi thực tế
- Phép tính, điều kiện, return value sai logic
- Hardcode secret/token/password
- Thiếu validate input
- Có thể gây exception chưa được xử lý
- Duplicate code hoặc naming mơ hồ
- Thay đổi test nhưng không sửa code, hoặc sửa code nhưng test không cover
- Điều kiện if/else dễ gây bug ở edge case
- Magic number, string hardcode, hoặc giá trị default nguy hiểm

Trả về JSON theo schema sau:
{{
  "summary": "Tóm tắt ngắn gọn thay đổi trong PR (1-2 câu)",
  "risk_level": "LOW | MEDIUM | HIGH",
  "risk_score": 0,
  "bugs": [
    "Mô tả bug 1 hoặc lỗi tiềm ẩn 1",
    "Mô tả bug 2 hoặc lỗi tiềm ẩn 2"
  ],
  "security_issues": [
    "Rủi ro bảo mật 1"
  ],
  "code_quality": [
    "Nhận xét chất lượng 1"
  ],
  "suggestions": [
    "Gợi ý 1",
    "Gợi ý 2"
  ],
  "decision": "BLOCK | WARN | APPROVE",
  "approved": true
}}

Quy tắc bổ sung cho output:
- "summary" phải tóm tắt thay đổi chính và đánh giá tổng quan ngắn gọn
- "bugs" chỉ chứa các vấn đề có khả năng gây sai chức năng
- "security_issues" chỉ chứa các vấn đề bảo mật thật sự
- "code_quality" chứa các điểm về readability, structure, naming, duplication, maintainability
- "suggestions" phải là hành động cụ thể, có thể sửa được
- "risk_score" phải là số nguyên từ 0 đến 100
- "decision" chỉ được là BLOCK, WARN hoặc APPROVE
- Nếu "decision" = "BLOCK" thì "approved" phải là false
- Nếu "risk_level" = "HIGH" thì "risk_score" nên từ 70 trở lên
- Nếu "risk_level" = "LOW" thì "risk_score" nên dưới 40
- Nếu có bug logic rõ ràng hoặc security issue nghiêm trọng thì "decision" phải là "BLOCK"
- "approved" = false nếu có bất kỳ bug logic rõ ràng hoặc security issue quan trọng

Chỉ trả về JSON.
"""


def normalize_analysis(analysis: dict) -> dict:
    """
    Chuẩn hóa dữ liệu phân tích từ LLM để tránh lỗi do sai kiểu hoặc thiếu field.
    """
    normalized = {
        "summary": str(analysis.get("summary", "Không có tóm tắt.")),
        "risk_level": str(analysis.get("risk_level", "MEDIUM")).upper(),
        "risk_score": analysis.get("risk_score", 0),
        "bugs": analysis.get("bugs", []),
        "security_issues": analysis.get("security_issues", []),
        "code_quality": analysis.get("code_quality", []),
        "suggestions": analysis.get("suggestions", []),
        "decision": str(analysis.get("decision", "WARN")).upper(),
        "approved": analysis.get("approved", False),
    }

    try:
        normalized["risk_score"] = int(normalized["risk_score"])
    except (TypeError, ValueError):
        normalized["risk_score"] = 0

    normalized["risk_score"] = max(0, min(100, normalized["risk_score"]))

    if normalized["risk_level"] not in {"LOW", "MEDIUM", "HIGH"}:
        normalized["risk_level"] = "MEDIUM"

    if normalized["decision"] not in {"BLOCK", "WARN", "APPROVE"}:
        normalized["decision"] = "WARN"

    for field in ["bugs", "security_issues", "code_quality", "suggestions"]:
        value = normalized[field]
        if isinstance(value, list):
            normalized[field] = [str(item).strip() for item in value if str(item).strip()]
        elif value:
            normalized[field] = [str(value).strip()]
        else:
            normalized[field] = []

    if isinstance(normalized["approved"], str):
        normalized["approved"] = normalized["approved"].strip().lower() == "true"
    else:
        normalized["approved"] = bool(normalized["approved"])

    if normalized["decision"] == "BLOCK":
        normalized["approved"] = False

    if normalized["decision"] == "APPROVE" and normalized["risk_level"] == "HIGH":
        normalized["decision"] = "WARN"

    return normalized


def format_review_comment(analysis: dict, pr_number: int) -> str:
    """
    Định dạng kết quả phân tích thành Markdown.

    Args:
        analysis: Dict chứa kết quả phân tích từ LLM
        pr_number: Số PR để hiển thị

    Returns:
        Chuỗi Markdown
    """
    risk = analysis.get("risk_level", "UNKNOWN")
    risk_score = analysis.get("risk_score", 0)
    decision = analysis.get("decision", "WARN")
    approved = analysis.get("approved", False)

    risk_icon = {
        "LOW": "GREEN",
        "MEDIUM": "YELLOW",
        "HIGH": "RED",
    }.get(risk, "GREY")

    status_line = "APPROVED" if approved else "CHANGES REQUESTED"

    def render_list(items: list, fallback: str = "Không phát hiện vấn đề.") -> str:
        if not items:
            return f"- {fallback}"
        return "\n".join(f"- {item}" for item in items)

    return f"""## AI PR Review #{pr_number}

**Trạng thái:** {status_line}  
**Decision:** {decision}  
**Mức độ rủi ro:** {risk_icon} {risk}  
**Risk score:** {risk_score}/100  

### Tóm tắt
{analysis.get('summary', 'Không có tóm tắt.')}

### Bug / Logic Error
{render_list(analysis.get('bugs', []))}

### Bảo mật
{render_list(analysis.get('security_issues', []))}

### Chất lượng code
{render_list(analysis.get('code_quality', []))}

### Gợi ý cải thiện
{render_list(analysis.get('suggestions', []))}
"""


def main() -> None:
    """
    Thực hiện PR Analyzer: lấy diff, phân tích, gửi comment lên PR.
    """
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("REPO", "")
    pr_number_str = os.getenv("PR_NUMBER", "")

    if not all([token, repo, pr_number_str]):
        logger.error("Thiếu biến môi trường: GITHUB_TOKEN, REPO, PR_NUMBER.")
        sys.exit(1)

    try:
        pr_number = int(pr_number_str)
    except ValueError:
        logger.error("PR_NUMBER không hợp lệ: %s", pr_number_str)
        sys.exit(1)

    logger.info("Bắt đầu phân tích PR #%d trên %s", pr_number, repo)

    diff = get_pr_diff(repo, pr_number, token)
    if not diff:
        logger.warning("Diff rỗng, bỏ qua phân tích.")
        sys.exit(0)

    prompt = build_review_prompt(diff)
    raw_response = call_llm(prompt, max_tokens=1000)

    if not raw_response:
        logger.warning("LLM không trả về kết quả. Post notice comment và exit gracefully.")
        notice = f"""## AI PR Review — #{pr_number}
Groq API unavailable.
"""
        post_pr_comment(repo, pr_number, token, notice)
        sys.exit(0)

    analysis = parse_json_response(raw_response)
    if not analysis:
        logger.warning(
            "Không thể parse JSON từ LLM. Post notice và exit gracefully. Raw: %s",
            raw_response[:300],
        )
        notice = f"""## AI PR Review — #{pr_number}
Could not parse response.
"""
        post_pr_comment(repo, pr_number, token, notice)
        sys.exit(0)

    analysis = normalize_analysis(analysis)

    comment_body = format_review_comment(analysis, pr_number)
    success = post_pr_comment(repo, pr_number, token, comment_body)

    if not success:
        logger.warning("Failed to post comment, but exiting gracefully (exit 0).")
        sys.exit(0)

    decision = analysis.get("decision", "WARN")
    risk_level = analysis.get("risk_level", "MEDIUM")
    risk_score = analysis.get("risk_score", 0)

    if decision == "BLOCK":
        logger.warning(
            "PR bị AI đánh giá BLOCK. risk_level=%s, risk_score=%s. Fail workflow để chặn merge.",
            risk_level,
            risk_score,
        )
        sys.exit(1)

    logger.info(
        "PR Analyzer hoàn thành. decision=%s, risk_level=%s, risk_score=%s",
        decision,
        risk_level,
        risk_score,
    )


if __name__ == "__main__":
    main()