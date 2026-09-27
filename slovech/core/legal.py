"""Published legal document versions and public paths."""

import hashlib

from slovech.core.config import ROOT

LEGAL_DIR = ROOT / "docs" / "legal"
DOCUMENTS = {
    "terms": LEGAL_DIR / "terms.md",
    "privacy": LEGAL_DIR / "privacy.md",
    "consent": LEGAL_DIR / "consent.md",
}


def document_version(kind: str) -> str:
    return document_snapshot(kind)[0]


def document_snapshot(kind: str) -> tuple[str, str, str | None]:
    content = DOCUMENTS[kind].read_text(encoding="utf-8")
    privacy = DOCUMENTS["privacy"].read_text(encoding="utf-8") if kind == "consent" else None
    version = hashlib.sha256((content + (privacy or "")).encode("utf-8")).hexdigest()
    return version, content, privacy


def public_url(domain: str, kind: str) -> str:
    return f"{domain}/legal/{kind}"


def archived_snapshots():
    """Keep the exact texts underlying past acceptance hashes, without user identifiers."""
    for directory in sorted((LEGAL_DIR / "archive").glob("*")):
        for kind in ("terms", "consent"):
            content = (directory / f"{kind}.md").read_text(encoding="utf-8")
            privacy = (
                (directory / "privacy.md").read_text(encoding="utf-8")
                if kind == "consent"
                else None
            )
            version = hashlib.sha256((content + (privacy or "")).encode("utf-8")).hexdigest()
            yield version, kind, content, privacy
