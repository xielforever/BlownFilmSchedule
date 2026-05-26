from __future__ import annotations

import argparse
from pathlib import Path


ALLOWED_STATUSES = {
    "draft",
    "active",
    "implemented",
    "verified",
    "superseded",
    "archived",
}

EVIDENCE_REQUIRED_STATUSES = {"implemented", "verified"}


def _normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/")


def _parse_register_rows(registry_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    in_register = False
    for raw_line in registry_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "## Document Register":
            in_register = True
            continue
        if in_register and line.startswith("## "):
            break
        if not in_register or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() in {"path", "---"}:
            continue
        if set(cells[0]) == {"-"}:
            continue
        rows.append({
            "path": _normalize_path(cells[0]),
            "status": cells[1].strip().lower(),
            "evidence": cells[2].strip(),
        })
    return rows


def _root_docs(root: Path, registry_path: Path) -> set[str]:
    docs_dir = root / "docs"
    if not docs_dir.exists():
        return set()
    registry_rel = registry_path.relative_to(root).as_posix()
    return {
        path.relative_to(root).as_posix()
        for path in docs_dir.glob("*.md")
        if path.relative_to(root).as_posix() != registry_rel
    }


def validate_document_status(root: Path, registry_path: Path) -> list[str]:
    issues: list[str] = []
    if not registry_path.exists():
        return [f"registry does not exist: {registry_path}"]

    rows = _parse_register_rows(registry_path)
    registered_paths: set[str] = set()
    for row in rows:
        doc_path = row["path"]
        status = row["status"]
        evidence = row["evidence"]
        registered_paths.add(doc_path)

        if status not in ALLOWED_STATUSES:
            issues.append(f"unknown status '{status}' for {doc_path}")
        if not (root / doc_path).exists():
            issues.append(f"registered path does not exist: {doc_path}")
        if status in EVIDENCE_REQUIRED_STATUSES and evidence in {"", "-"}:
            issues.append(f"{status} document lacks evidence: {doc_path}")

    for doc_path in sorted(_root_docs(root, registry_path) - registered_paths):
        issues.append(f"root docs file missing from registry: {doc_path}")

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate root documentation status registry.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument(
        "--registry",
        default="docs/document-status-governance.md",
        help="Documentation status registry path.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    registry_path = (root / args.registry).resolve()
    issues = validate_document_status(root, registry_path)
    for issue in issues:
        print(issue)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
