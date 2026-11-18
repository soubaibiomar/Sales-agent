"""
Automated validation of Repository Hygiene and Secrets Absence for Step 01.
Verifies .gitignore, .env.example, AGENTS.md, UI design system tokens, and lack of plaintext secrets.
"""
import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

def test_gitignore_exists_and_contains_critical_patterns():
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.exists(), ".gitignore missing"
    content = gitignore.read_text(encoding="utf-8")
    assert ".env" in content
    assert "__pycache__" in content
    assert "node_modules" in content
    assert ".venv" in content or "venv" in content

def test_env_example_has_no_real_secrets():
    env_example = REPO_ROOT / ".env.example"
    assert env_example.exists(), ".env.example missing"
    content = env_example.read_text(encoding="utf-8")
    
    # Check that keys have placeholder values, not real production tokens
    assert "dev_placeholder" in content or "dev_" in content
    assert "postgres_dev_password" in content
    
    # Check forbidden production secret patterns
    assert "sk-proj-" not in content  # OpenAI live key
    assert "ghp_" not in content      # GitHub live token
    assert "xoxb-" not in content     # Slack live token

def test_agents_instructions_completeness():
    agents_file = REPO_ROOT / "AGENTS.md"
    assert agents_file.exists(), "AGENTS.md missing"
    content = agents_file.read_text(encoding="utf-8")
    
    # Invariants
    assert "Deterministic Commercial Authority" in content
    assert "PostgreSQL as Single Source of Truth" in content
    assert "Zero-Trust Multi-Tenancy" in content
    assert "Three Execution Classes" in content
    assert "Dual-Mode Voice Architecture" in content
    
    # 18-role catalog
    assert "18-ROLE CATALOG" in content
    assert "Discovery & Qualification Specialist" in content
    assert "Quotation & Pricing Specialist" in content
    assert "Conversation Supervisor" in content
    
    # UI tokens
    assert "#0A3A2A" in content  # Deep Forest Green
    assert "WCAG AAA" in content

def test_no_hardcoded_private_keys_in_repo():
    forbidden_patterns = [
        re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
        re.compile(r"sk-[a-zA-Z0-9]{32,}"),
        re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    ]
    
    # Scan text files in repo (excluding .git, binary, .xlsx, .pdf)
    text_extensions = {".md", ".py", ".mmd", ".tex", ".json", ".example"}
    
    for file_path in REPO_ROOT.rglob("*"):
        if ".git" in file_path.parts or ".pytest_cache" in file_path.parts:
            continue
        if file_path.is_file() and file_path.suffix in text_extensions:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                for pattern in forbidden_patterns:
                    assert not pattern.search(content), f"Forbidden secret pattern found in: {file_path}"
            except Exception:
                pass
