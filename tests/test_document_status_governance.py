from pathlib import Path

from scripts.validate_doc_status import validate_document_status


def test_document_status_registry_requires_known_status_and_existing_path(tmp_path: Path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    registry = docs_dir / "document-status-governance.md"
    registry.write_text(
        "\n".join([
            "# Document Status Governance",
            "",
            "## Document Register",
            "",
            "| Path | Status | Evidence |",
            "| --- | --- | --- |",
            "| docs/plan.md | unknown | pytest |",
            "| docs/missing.md | draft | - |",
        ]),
        encoding="utf-8",
    )

    issues = validate_document_status(tmp_path, registry)

    assert "unknown status 'unknown' for docs/plan.md" in issues
    assert "registered path does not exist: docs/missing.md" in issues


def test_document_status_registry_requires_evidence_for_verified_docs(tmp_path: Path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "done.md").write_text("# Done\n", encoding="utf-8")
    registry = docs_dir / "document-status-governance.md"
    registry.write_text(
        "\n".join([
            "# Document Status Governance",
            "",
            "## Document Register",
            "",
            "| Path | Status | Evidence |",
            "| --- | --- | --- |",
            "| docs/done.md | verified | - |",
        ]),
        encoding="utf-8",
    )

    issues = validate_document_status(tmp_path, registry)

    assert "verified document lacks evidence: docs/done.md" in issues


def test_document_status_registry_requires_root_docs_coverage(tmp_path: Path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "covered.md").write_text("# Covered\n", encoding="utf-8")
    (docs_dir / "uncovered.md").write_text("# Uncovered\n", encoding="utf-8")
    registry = docs_dir / "document-status-governance.md"
    registry.write_text(
        "\n".join([
            "# Document Status Governance",
            "",
            "## Document Register",
            "",
            "| Path | Status | Evidence |",
            "| --- | --- | --- |",
            "| docs/covered.md | draft | - |",
        ]),
        encoding="utf-8",
    )

    issues = validate_document_status(tmp_path, registry)

    assert "root docs file missing from registry: docs/uncovered.md" in issues
