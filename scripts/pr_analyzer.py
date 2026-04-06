from __future__ import annotations

import os
import sys
import logging
from github import Github, GithubException
from ai_engine import call_llm, parse_json_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
MAX_DIFF_CHARS = 4000  

def get_pr_diff(repo_name: str, pr_number: int, token: str) -> str:
    """
    Lấy nội dung diff của PR từ Github API
    Arguments:
        repo_name: Tên của repo dạng 'owner/repo'
        pr_number: Số thứ tự định danh của PUll REQUEST
        token: GitHub personal access token.
    Returns:
        Chuỗi diff, tối đa phụ thuộc vào MAX_DIFF_CHARS, hoặc trả về chuỗi rỗng nếu lỗi
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
            logger.info("Do diff quá dài, cắt bớt còn %d ký tự.", MAX_DIFF_CHARS)
            return full_diff[:MAX_DIFF_CHARS] 
        return full_diff

    except GithubException as exc:
        logger.error("Lỗi khi lấy PR diff: %s", exc)
        return ""


def post_pr_comment(repo_name: str, pr_number: int, token: str, body: str) -> bool:
    """
    Post comment lên Pull Request trên GitHub.
        body: Noi dung comment (Markdown).
    """
    try:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        pr.create_issue_comment(body)
        logger.info("Đã post comment lên PR số #%d thanh cong.", pr_number)
        return True
    except GithubException as exc:
        logger.error("Lỗi khi comment: %s", exc)
        return False

def build_review_prompt(diff: str) -> str:
    """
    Hàm để xây dựng prompt 
    Args:
        diff: Nội dung của diff của PR.
    Returns:
        Chuỗi prompt hoàn chỉnh
    """
    return f"""Bạn là một senior DevOps engineer, security-minded code reviewer và code reviewer với nhiều năm kinh nghiệm làm dự án trong môi trường production.
Nhiệm vụ: Hãy phân tích các đoạn code diff dưới đây như một reviewer thực tế và khó tính 
Chỉ đưa ra nhận xét dựa trên bằng chứng xuất hiện trong diff, không tự đoán mò và trả về kết quả chính xác theo định dạng JSON.
Không được khen xã giao, không được nói chung chung

Code diff:
{diff}

Mục tiêu reviewL 
1. Tìm bug hoặc logic error có khả năng gây sai chức năng
2. Tìm edge case chưa được xử lí
3. Tìm rủi ro bảo mật hoặc lỗ hổng có liên quan đến secret, token, input validation, exception handling
4. Đánh giá chất lượng code: naming, readabiliyy, duplication, maintainability, structure
5. TÌm thay đổi có thể gây vỡ backward compatibility, gây tác dụng phụ hoặc làm sai hành vi mong đợi
6. Đưa ra đề xuất sửa cụ thể, ưu tiên đề xuất có thể áp dụng ngay

Các nguyên tắc bắt buộc: 
- Chỉ đánh giá dựa trên diff được cung cấp
- Nếu không đủ bằng chứng, hãy giữ mức độ cẩn trọng và hỏi lại
- Nếu thay đổi có dấu hiệu sai logic, hãy đưa vào trường "bugs"
- Nếu thay đổi có nguy cơ nhưng chưa chắc chắn, đưa vào "code_quality" hoặc "suggestions", không khẳng định quá mức
- Không viết markdown
- Không thêm bất kì văn bản nào ngoài kiểu JSON
- Mỗi mục trong list phải là câu ngắn, rõ ràng, cụ thể
- Nếu không có vấn đề nào ở một mức, trả về list rỗng cho mức đó
- Trường "Approved" chỉ được đặt là true khi không có bug logic, không có security issue nghiêm trọng và không có vấn đề chất lượng đáng kể

Tiêu chí đánh giá mức độ rủi ro: 
LOW: thay đổi nhỏ, ít khả năng gây lỗi, không có dấu hiệu bug, security
MEDIUML có một vài điểm đáng nghi, có thể gây lỗi trong một số trường hợp
HIGH: có dấu hiệu rõ ràng của bug logic, security risk, hoặc thay đổi để cản trở hành vi mong đợi 

Chú các các mẫu lỗi thường gặp: 
- Têm hàm không đúng hành vi thực tế
- Phép tính, điều kiện, return value sai logic
- Hardcode secret/token/password
- Thiếu validate input 
- Có thể gây exception chưa được xử lí
- Duplivate code hoặc naming mơ hồ 
- Thay đổi test nhưng không sửa code, hoặc sửa code nhưng test không cover
- Điều kiện if/else để gây bug ở edge case
- Magic number, string hardcode, hoặc giá trị default nguy hiểm
Trả về JSON theo schema sau:
{{
  "summary": "Tóm tắt ngắn gọn thay đổi trong PR,(1-2 câu)",
  "risk_level": "LOW | MEDIUM | HIGH",
  "bugs": [
      "Mo tả bug 1 hoặc lỗi tiềm ẩn 1",
      "Mô tả bug 2 hoặc lỗi tiềm ẩn 2",
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
  "approved": true
}}

Quy tắc bổ sug cho output:
- "summary" phải tóm tắt thay đổi chính và đánh giá tổng quan ngắn gọn
- "bugs" chỉ chứa các vấn đề có khả năng gây sai chức năng
- "security_issues" chỉ chứa các vấn đề bảo mật thật sự
- "code_quality" chứa các điểm về readability, structure, naming, duplication, maintainability
- "suggestions" phải là hành động cụ thể, có thể sửa được
- "approved" = false nếu có bất kì bug logic rõ ràng hoặc security issue quan trọng.

Chỉ trả về JSON.
"""


def format_review_comment(analysis: dict, pr_number: int) -> str:
    """
    Định dạng kết quả phân tích thành Markdown.
    Args:
        analysis: Dict chứa kết quả phân tích từ LLM.
        pr_number:SỐ PR để hiển thị.
    Returns:
        Chuỗi Markdown.
    """
    risk = analysis.get("risk_level", "UNKNOWN")
    risk_icon = {"LOW": "GREEN", "MEDIUM": "YELLOW", "HIGH": "RED"}.get(risk, "GREY")
    approved = analysis.get("approved", False)
    status_line = "APPROVED" if approved else "CHANGES REQUESTED"

    def render_list(items: list, fallback: str = "Không phát hiện vấn đề.") -> str:
        if not items:
            return f"- {fallback}"
        return "\n".join(f"- {item}" for item in items)

    return f"""AI PR Review {pr_number}

**Trạng thái:** {status_line}
**Mức độ rủi ro:** {risk_icon} {risk}

### Tóm tắt 
{analysis.get('summary', 'Khong co tom tat.')}

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
    """Thực hiện PR Analyzer: Lấy diff, phân tích, gửi comment PR."""
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

    logger.info("Bắt đầu phân tích PR #%d tren %s", pr_number, repo)

    diff = get_pr_diff(repo, pr_number, token)
    if not diff:
        logger.warning("Diff rỗng, bỏ quan phân tích.")
        sys.exit(0)

    prompt = build_review_prompt(diff)
    raw_response = call_llm(prompt, max_tokens=1000)

    if not raw_response:
        logger.warning("LLM không trả về kết quả. Post notice comment và exit gracefully.")
        notice = f"""## AI PR Review — #{pr_number}
        Groq API unavailable
        """
        post_pr_comment(repo, pr_number, token, notice)
        sys.exit(0) 

    analysis = parse_json_response(raw_response)
    if not analysis:
        logger.warning("Không thể parse JSON từ LLM. Post notice và exit gracefully. Raw: %s", raw_response[:300])
        notice = f"""## AI PR Review — #{pr_number}
        Could not parse response.
        """
        post_pr_comment(repo, pr_number, token, notice)
        sys.exit(0)  

    comment_body = format_review_comment(analysis, pr_number)
    success = post_pr_comment(repo, pr_number, token, comment_body)

    if not success:
        logger.warning("Failed to post comment, but exiting gracefully (exit 0).")
        sys.exit(0)

    logger.info("PR Analyzer hoàn thành.")


if __name__ == "__main__":
    main()
