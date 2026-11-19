"""Filesystem locations. The server reads `contracts/kb` and `server/config` relative to the repository root
(the Docker image keeps the same layout: /repo/contracts, /repo/server)."""

from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVER_DIR.parent
CONFIG_DIR = SERVER_DIR / "config"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
CONTRACTS_DIR = REPO_ROOT / "contracts"
KB_LISTS_DIR = CONTRACTS_DIR / "kb"
LLM_FIXTURES_DIR = SERVER_DIR / "tests" / "llm_fixtures"
