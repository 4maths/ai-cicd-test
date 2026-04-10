from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

import yaml
from github import Github, GithubException

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

OVERRIDE_LABEL = "security-risk-accepted"

DEFAULT_RULES = [
    {
        "id": "hardcoded_secret",
        "description": "Phát hiện secret/token/password hardcode",
        "pattern": r'(?i)(api_key|apikey|token|secret|password|access_token|refresh_token|github_token)\s*[:=]\s*["\'][^"\']+["\']',
        "severity": "HIGH",
        "why_it_matters": "Secret hardcode có thể bị lộ qua git history, log hoặc người có quyền truy cập repo.",
        "suggested_fix": "Chuyển secret sang biến môi trường hoặc secret manager (GitHub Secrets, Vault, AWS Secrets Manager...).",
        "allow_override": False,
    },
    {
        "id": "debug_mode_enabled",
        "description": "Phát hiện debug mode bật trong code",
        "pattern": r'(?i)(debug\s*=\s*True|app\.run\(.*debug\s*=\s*True)',
        "severity": "MEDIUM",
        "why_it_matters": "Debug mode có thể làm lộ stack trace hoặc thông tin nội bộ trong production.",
        "suggested_fix": "Tắt debug mode ở production và điều khiển bằng biến môi trường.",
        "allow_override": True,
    },
    {
        "id": "subprocess_shell_true",
        "description": "Phát hiện subprocess shell=True có thể gây command injection",
        "pattern": r'(?s)subprocess\.(run|Popen)\(.*?shell\s*=\s*True',
        "severity": "HIGH",
        "why_it_matters": "shell=True có thể dẫn tới command injection nếu input không được kiểm soát.",
        "suggested_fix": "Tránh dùng shell=True, truyền command dưới dạng list thay vì string.",
        "allow_override": False,
    },
]

DEFAULT_PATH_CONFIG = {
    "include_paths": ["scripts/", "app.py"],
    "exclude_paths": ["tests/", "config/", ".github/", ".venv/", "docs/", "examples/"],
    "exclude_extensions": [".md", ".txt", ".json", ".lock"],
    "exclude_file_patterns": [r".*\.min\.js$", r".*generated.*"],
}


def get_github_client(token: str) -> Github:
    return Github(token)


def get_pr(repo_name: str, pr_number: int, token: str):
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    return repo.get_pull(pr_number)


def has_override_label(pr) -> bool:
    labels = [label.name for label in pr.get_labels()]
    return OVERRIDE_LABEL in labels


def load_rules(config_path: str = "config/security_rules.yml") -> list[dict]:
    path = Path(config_path)
    if not path.exists():
        logger.warning("Không tìm thấy %s. Dùng default rules.", config_path)
        return DEFAULT_RULES

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        rules = data.get("rules", [])
        if not isinstance(rules, list) or not rules:
            logger.warning("Rules trong %s không hợp lệ. Dùng default rules.", config_path)
            return DEFAULT_RULES

        logger.info("Đã load %d security rules từ %s", len(rules), config_path)
        return rules
    except Exception as exc:
        logger.error("Lỗi khi load security rules từ %s: %s. Dùng default rules.", config_path, exc)
        return DEFAULT_RULES


def load_path_config(config_path: str = "config/security_paths.yml") -> dict:
    path = Path(config_path)
    if not path.exists():
        logger.warning("Không tìm thấy %s. Dùng default path config.", config_path)
        return DEFAULT_PATH_CONFIG

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        config = {
            "include_paths": data.get("include_paths", DEFAULT_PATH_CONFIG["include_paths"]),
            "exclude_paths": data.get("exclude_paths", DEFAULT_PATH_CONFIG["exclude_paths"]),
            "exclude_extensions": data.get("exclude_extensions", DEFAULT_PATH_CONFIG["exclude_extensions"]),
            "exclude_file_patterns": data.get(
                "exclude_file_patterns",
                DEFAULT_PATH_CONFIG["exclude_file_patterns"],
            ),
        }

        logger.info("Đã load path config từ %s", config_path)
        return config
    except Exception as exc:
        logger.error("Lỗi khi load security path config từ %s: %s. Dùng default path config.", config_path, exc)
        return DEFAULT_PATH_CONFIG


def should_scan_file(filename: str, path_config: dict) -> bool:
    include_paths = path_config.get("include_paths", [])
    exclude_paths = path_config.get("exclude_paths", [])
    exclude_extensions = path_config.get("exclude_extensions", [])
    exclude_file_patterns = path_config.get("exclude_file_patterns", [])

    if include_paths:
        matched_include = any(filename == item or filename.startswith(item) for item in include_paths)
        if not matched_include:
            return False

    if any(filename.startswith(prefix) for prefix in exclude_paths):
        return False

    if any(filename.endswith(ext) for ext in exclude_extensions):
        return False

    for pattern in exclude_file_patterns:
        if re.match(pattern, filename):
            return False

    return True


def get_pr_files(repo_name: str, pr_number: int, token: str) -> list[tuple[str, str]]:
    try:
        pr = get_pr(repo_name, pr_number, token)

        files_data: list[tuple[str, str]] = []
        for changed_file in pr.get_files():
            if changed_file.patch:
                files_data.append((changed_file.filename, changed_file.patch))
        return files_data

    except GithubException as exc:
        logger.error("Lỗi khi lấy file PR: %s", exc)
        return []


def normalize_rule(rule: dict) -> dict:
    return {
        "id": str(rule.get("id", "unknown_rule")).strip(),
        "description": str(rule.get("description", "Không có mô tả")).strip(),
        "pattern": str(rule.get("pattern", "")).strip(),
        "severity": str(rule.get("severity", "LOW")).strip().upper(),
        "why_it_matters": str(rule.get("why_it_matters", "")).strip(),
        "suggested_fix": str(rule.get("suggested_fix", "")).strip(),
        "allow_override": bool(rule.get("allow_override", True)),
    }


def extract_snippet(text: str, pattern: str, max_len: int = 160) -> str:
    try:
        match = re.search(pattern, text)
        if not match:
            return ""

        start = max(match.start() - 40, 0)
        end = min(match.end() + 80, len(text))
        snippet = text[start:end].strip().replace("\n", " ")
        if len(snippet) > max_len:
            snippet = snippet[:max_len] + "..."
        return snippet
    except re.error:
        return ""


def scan_text(filename: str, text: str, rules: list[dict]) -> list[dict]:
    findings: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()

    for raw_rule in rules:
        rule = normalize_rule(raw_rule)
        pattern = rule["pattern"]
        if not pattern:
            logger.warning("Rule %s không có pattern hợp lệ, bỏ qua.", rule["id"])
            continue

        try:
            if re.search(pattern, text):
                dedup_key = (filename, rule["id"])
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                findings.append(
                    {
                        "file": filename,
                        "rule_id": rule["id"],
                        "description": rule["description"],
                        "severity": rule["severity"],
                        "why_it_matters": rule["why_it_matters"],
                        "suggested_fix": rule["suggested_fix"],
                        "allow_override": rule["allow_override"],
                        "snippet": extract_snippet(text, pattern),
                    }
                )
        except re.error as exc:
            logger.error("Regex không hợp lệ ở rule %s: %s", rule["id"], exc)

    return findings


def format_security_comment(findings: list[dict], pr_number: int, override: bool) -> str:
    if not findings:
        return f"""## AI Security Scan — PR #{pr_number}

**Decision:** APPROVE  
Không phát hiện vấn đề bảo mật rõ ràng trong diff hiện tại.

---
AI CI/CD Assistant — Security Scanner
"""

    high_count = sum(1 for f in findings if f["severity"] == "HIGH")
    medium_count = sum(1 for f in findings if f["severity"] == "MEDIUM")
    low_count = sum(1 for f in findings if f["severity"] == "LOW")

    decision = "BLOCK" if high_count > 0 and not override else "WARN"

    lines = []
    for item in findings:
        snippet_block = ""
        if item.get("snippet"):
            snippet_block = f'\n  - Snippet: `{item["snippet"]}`'

        lines.append(
            f"""- **{item['severity']}** | `{item['file']}` | {item['description']} (`{item['rule_id']}`)
  - Why it matters: {item['why_it_matters']}
  - Suggested fix: {item['suggested_fix']}{snippet_block}
"""
        )

    override_text = ""
    if override:
        override_text = f"""
### Override
PR có label `{OVERRIDE_LABEL}` → chấp nhận rủi ro, không chặn merge.
"""

    return f"""## AI Security Scan — PR #{pr_number}

**Decision:** {decision}  
**Tóm tắt:** Phát hiện {len(findings)} vấn đề (HIGH: {high_count}, MEDIUM: {medium_count}, LOW: {low_count})

### Findings
{chr(10).join(lines)}
{override_text}
---
AI CI/CD Assistant — Security Scanner
"""


def post_pr_comment(repo_name: str, pr_number: int, token: str, body: str) -> bool:
    try:
        pr = get_pr(repo_name, pr_number, token)
        pr.create_issue_comment(body)
        logger.info("Đã post security comment lên PR #%d.", pr_number)
        return True
    except GithubException as exc:
        logger.error("Lỗi khi post comment: %s", exc)
        return False


def main() -> None:
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("REPO", "")
    pr_number_str = os.getenv("PR_NUMBER", "")

    if not all([token, repo, pr_number_str]):
        logger.error("Thiếu biến môi trường: GITHUB_TOKEN, REPO hoặc PR_NUMBER.")
        sys.exit(1)

    try:
        pr_number = int(pr_number_str)
    except ValueError:
        logger.error("PR_NUMBER không hợp lệ: %s", pr_number_str)
        sys.exit(1)

    rules = load_rules("config/security_rules.yml")
    path_config = load_path_config("config/security_paths.yml")

    try:
        pr = get_pr(repo, pr_number, token)
    except GithubException as exc:
        logger.error("Không thể lấy PR #%d: %s", pr_number, exc)
        sys.exit(1)

    override = has_override_label(pr)
    logger.info("Override label status: %s", override)

    files_data = get_pr_files(repo, pr_number, token)
    if not files_data:
        logger.warning("Không lấy được file diff từ PR hoặc PR không có patch.")
        sys.exit(0)

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
        sys.exit(0)

    high_findings = [f for f in all_findings if f["severity"] == "HIGH"]

    if high_findings and not override:
        logger.warning("Có HIGH và không override → fail workflow.")
        sys.exit(1)

    logger.info("Security Scanner hoàn thành.")


if __name__ == "__main__":
    main()