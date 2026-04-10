from __future__ import annotations

import logging
import os
import sys

from github import Github, GithubException

from ai_engine import call_llm, parse_json_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MAX_LOG_CHARS = 3000


def get_workflow_logs(repo_name: str, run_id: int, token: str) -> str:
    """
    Lấy log workflow ở mức job/step summary từ GitHub Actions.

    Arguments:
        repo_name: Tên repo dạng 'owner/repo'
        run_id: ID của workflow run
        token: GitHub token

    Returns:
        Chuỗi log tóm tắt, hoặc chuỗi rỗng nếu lỗi
    """
    try:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        run = repo.get_workflow_run(run_id)

        log_parts: list[str] = []
        for job in run.jobs():
            job_header = f"JOB: {job.name} | Status: {job.conclusion}"
            step_logs: list[str] = []

            for step in job.steps:
                step_logs.append(f"[Step: {step.name} | {step.conclusion}]")

            log_parts.append(job_header + "\n" + "\n".join(step_logs))

        combined = "\n\n".join(log_parts)

        if len(combined) > MAX_LOG_CHARS:
            logger.info("Log quá dài, chỉ lấy %d ký tự cuối.", MAX_LOG_CHARS)
            return "...\n" + combined[-MAX_LOG_CHARS:]

        return combined

    except GithubException as exc:
        logger.error("Lỗi khi lấy workflow logs: %s", exc)
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
        logger.error("Lỗi khi post comment lên PR: %s", exc)
        return False


def build_log_prompt(log_content: str) -> str:
    """
    Xây dựng prompt để gửi sang LLM cho bài toán phân tích log CI fail.
    """
    return f"""Bạn là một DevOps engineer giàu kinh nghiệm trong việc debug CI/CD pipeline, build failure, test failure và workflow automation trên GitHub Actions.

Nhiệm vụ:
Phân tích log CI thất bại dưới đây và xác định nguyên nhân gốc rễ một cách chính xác, ngắn gọn, có căn cứ.
Chỉ được dựa trên thông tin xuất hiện trong log.
Không suy đoán quá mức.
Không viết chung chung.
Không thêm lời mở đầu hay giải thích ngoài JSON.

Log CI:
{log_content}

Mục tiêu phân tích:
1. Xác định chính xác step hoặc job thất bại
2. Phân loại lỗi theo đúng bản chất
3. Giải thích nguyên nhân gốc rễ rõ ràng, ngắn gọn, dễ hiểu
4. Đề xuất cách sửa lỗi cụ thể, có thể thực hiện ngay
5. Đề xuất cách phòng tránh lỗi này tái diễn trong tương lai

Nguyên tắc bắt buộc:
- Chỉ phân tích dựa trên log được cung cấp
- Nếu log không đủ thông tin, phải thể hiện sự thận trọng trong phần root_cause
- Không bịa thêm bối cảnh không có trong log
- Nếu lỗi nằm ở test, dependency, cấu hình workflow, hoặc network/API, cần phân loại đúng
- "suggested_fix" phải mang tính hành động, không được quá chung chung
- "prevention" phải là biện pháp thực tế để tránh lỗi lặp lại
- "fix_command" chỉ nên điền khi có lệnh cụ thể hợp lý để áp dụng
- Nếu không có command phù hợp rõ ràng, trả về chuỗi rỗng cho "fix_command"

Hướng dẫn phân loại "error_type":
- "build_error": lỗi trong quá trình build hoặc compile
- "test_failure": lỗi do test fail, assertion fail, expected != actual
- "dependency_error": lỗi thiếu package, sai version, install dependency thất bại
- "config_error": lỗi cấu hình workflow, env variable, secret, path, permission
- "network_error": lỗi timeout, rate limit, API unavailable, kết nối thất bại
- "other": các lỗi còn lại không thuộc nhóm trên

Yêu cầu chất lượng output:
- "failed_step": phải ghi rõ tên step hoặc job thất bại nếu suy ra được từ log
- "root_cause": 2-3 câu, nêu đúng nguyên nhân gốc rễ, không lan man
- "suggested_fix": nêu từng hành động cụ thể để sửa
- "confidence": chỉ chọn HIGH khi log thể hiện nguyên nhân rất rõ ràng
- "confidence": chọn MEDIUM nếu có dấu hiệu mạnh nhưng chưa hoàn toàn chắc chắn
- "confidence": chọn LOW nếu log quá ít thông tin hoặc nguyên nhân chỉ là suy luận hợp lý
- "prevention": đưa ra biện pháp phòng tránh thực tế như thêm validation, cải thiện test, khóa version dependency, tăng logging, hoặc retry/backoff

Trả về đúng JSON theo schema sau:
{{
  "error_type": "build_error | test_failure | dependency_error | config_error | network_error | other",
  "failed_step": "Tên step hoặc job thất bại cụ thể",
  "root_cause": "Mô tả ngắn gọn nguyên nhân gốc rễ, tối đa 2-3 câu",
  "suggested_fix": "Hướng dẫn sửa lỗi cụ thể, rõ ràng, có thể làm ngay",
  "fix_command": "",
  "confidence": "HIGH | MEDIUM | LOW",
  "prevention": "Cách ngăn lỗi này tái diễn trong tương lai"
}}

Quy tắc bổ sung cho output:
- Nếu lỗi là dependency_error và suy ra được package thiếu, "fix_command" nên là lệnh như pip install <package>
- Nếu là test_failure, hãy chỉ ra test hoặc nhóm test fail nếu log thể hiện được
- Nếu là config_error, hãy chỉ ra biến môi trường, secret, path hoặc permission có vấn đề nếu log thể hiện được
- Nếu không đủ dữ liệu để xác định chính xác, phải giảm confidence
- Không thêm bất kỳ văn bản nào ngoài JSON hợp lệ

Chỉ trả về JSON hợp lệ. Không markdown. Không giải thích thêm.
"""


def normalize_analysis(analysis: dict) -> dict:
    """
    Chuẩn hóa dữ liệu phân tích từ LLM để tránh lỗi do sai kiểu hoặc thiếu field.
    """
    normalized = {
        "error_type": str(analysis.get("error_type", "other")).strip().lower(),
        "failed_step": str(analysis.get("failed_step", "Không xác định")).strip(),
        "root_cause": str(analysis.get("root_cause", "Không xác định được nguyên nhân gốc rễ.")).strip(),
        "suggested_fix": str(analysis.get("suggested_fix", "Chưa có gợi ý sửa cụ thể.")).strip(),
        "fix_command": str(analysis.get("fix_command", "")).strip(),
        "confidence": str(analysis.get("confidence", "LOW")).strip().upper(),
        "prevention": str(analysis.get("prevention", "Chưa có khuyến nghị phòng tránh.")).strip(),
    }

    valid_error_types = {
        "build_error",
        "test_failure",
        "dependency_error",
        "config_error",
        "network_error",
        "other",
    }
    if normalized["error_type"] not in valid_error_types:
        normalized["error_type"] = "other"

    if normalized["confidence"] not in {"HIGH", "MEDIUM", "LOW"}:
        normalized["confidence"] = "LOW"

    if not normalized["failed_step"]:
        normalized["failed_step"] = "Không xác định"

    if not normalized["root_cause"]:
        normalized["root_cause"] = "Không xác định được nguyên nhân gốc rễ."

    if not normalized["suggested_fix"]:
        normalized["suggested_fix"] = "Chưa có gợi ý sửa cụ thể."

    if not normalized["prevention"]:
        normalized["prevention"] = "Chưa có khuyến nghị phòng tránh."

    return normalized


def format_log_comment(analysis: dict, run_id: int) -> str:
    """
    Định dạng kết quả phân tích log thành Markdown để comment lên PR.
    """
    error_type = analysis.get("error_type", "other")
    failed_step = analysis.get("failed_step", "Không xác định")
    root_cause = analysis.get("root_cause", "Không xác định được nguyên nhân gốc rễ.")
    suggested_fix = analysis.get("suggested_fix", "Chưa có gợi ý sửa cụ thể.")
    fix_command = analysis.get("fix_command", "")
    confidence = analysis.get("confidence", "LOW")
    prevention = analysis.get("prevention", "Chưa có khuyến nghị phòng tránh.")

    confidence_icon = {
        "HIGH": "RED",
        "MEDIUM": "YELLOW",
        "LOW": "GREEN",
    }.get(confidence, "GREY")

    error_type_label = {
        "build_error": "Build Error",
        "test_failure": "Test Failure",
        "dependency_error": "Dependency Error",
        "config_error": "Config Error",
        "network_error": "Network Error",
        "other": "Other",
    }.get(error_type, "Other")

    fix_command_block = ""
    if fix_command:
        fix_command_block = f"""

### Lệnh gợi ý
```bash
{fix_command}
```"""

    return f"""## AI CI Log Analysis — Run #{run_id}

**Loại lỗi:** {error_type_label}  
**Step/job thất bại:** {failed_step}  
**Confidence:** {confidence_icon} {confidence}  

### Root cause
{root_cause}

### Suggested fix
{suggested_fix}{fix_command_block}

### Prevention
{prevention}
"""


def main() -> None:
    """
    Thực hiện Log Analyzer: lấy log workflow fail, phân tích, rồi post comment lên PR nếu có.
    """
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("REPO", "")
    run_id_str = os.getenv("RUN_ID", "")
    pr_number_str = os.getenv("PR_NUMBER", "")

    if not all([token, repo, run_id_str]):
        logger.error("Thiếu biến môi trường: GITHUB_TOKEN, REPO, hoặc RUN_ID.")
        sys.exit(1)

    try:
        run_id = int(run_id_str)
    except ValueError:
        logger.error("RUN_ID không hợp lệ: %s", run_id_str)
        sys.exit(1)

    pr_number: int | None = None
    if pr_number_str:
        try:
            pr_number = int(pr_number_str)
        except ValueError:
            logger.warning("PR_NUMBER không hợp lệ: %s", pr_number_str)

    logger.info("Bắt đầu phân tích log cho run #%d trên %s", run_id, repo)

    log_content = get_workflow_logs(repo, run_id, token)
    if not log_content:
        logger.warning("Log rỗng, bỏ qua phân tích.")
        sys.exit(0)

    prompt = build_log_prompt(log_content)
    raw_response = call_llm(prompt, max_tokens=1000)

    if not raw_response:
        logger.warning("LLM không trả về kết quả. Exit gracefully.")
        if pr_number:
            notice = f"""## AI CI Log Analysis — Run #{run_id}
Groq API unavailable.
"""
            post_pr_comment(repo, pr_number, token, notice)
        sys.exit(0)

    analysis = parse_json_response(raw_response)
    if not analysis:
        logger.warning("Không thể parse JSON từ LLM. Raw: %s", raw_response[:300])
        if pr_number:
            notice = f"""## AI CI Log Analysis — Run #{run_id}
Could not parse response.
"""
            post_pr_comment(repo, pr_number, token, notice)
        sys.exit(0)

    analysis = normalize_analysis(analysis)
    comment_body = format_log_comment(analysis, run_id)

    if pr_number:
        success = post_pr_comment(repo, pr_number, token, comment_body)
        if not success:
            logger.warning("Không post được comment lên PR, nhưng vẫn exit gracefully.")
            sys.exit(0)
    else:
        logger.info("Không có PR_NUMBER. In kết quả ra log:\n%s", comment_body)

    logger.info(
        "Log Analyzer hoàn thành. error_type=%s, failed_step=%s, confidence=%s",
        analysis.get("error_type"),
        analysis.get("failed_step"),
        analysis.get("confidence"),
    )


if __name__ == "__main__":
    main()