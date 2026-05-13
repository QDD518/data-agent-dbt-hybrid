"""SQL security validator — ensures only read-only queries pass through."""

import re

# Keywords that must NOT appear in user-submitted SQL
FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "REPLACE", "MERGE", "GRANT", "REVOKE",
    "COPY", "EXECUTE", "EXEC", "CALL", "VACUUM", "ANALYZE",
]

FORBIDDEN_PATTERNS = [
    r"--",           # SQL comments (can be used to bypass checks)
    r"/\*.*?\*/",    # block comments
    r";\s*(?!$)",    # multiple statements
]


class SQLSecurityError(Exception):
    """Raised when SQL fails security validation."""


def validate_sql(sql: str) -> None:
    """Raise SQLSecurityError if sql is not read-only."""
    if not sql or not sql.strip():
        raise SQLSecurityError("Empty SQL.")

    upper = sql.upper()

    # Check forbidden keywords as whole words
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            raise SQLSecurityError(f"Forbidden keyword: {kw}")

    # Only SELECT statements
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
        raise SQLSecurityError("Only SELECT / WITH queries allowed.")

    # Check for statement chaining
    if sql.strip().count(";") > 0:
        parts = [p.strip() for p in sql.strip().split(";") if p.strip()]
        if len(parts) > 1:
            raise SQLSecurityError("Multiple statements not allowed.")
