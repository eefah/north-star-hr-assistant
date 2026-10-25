"""Parse the policy Markdown files, chunk them by section and upload the chunks to Pinecone.

Usage:
    python ingest.py                    # baseline index: data/*.md only
    python ingest.py --include-expired  # adversarial run: also index negative_examples/*.md
    python ingest.py --dry-run          # parse and chunk only; print a summary, upload nothing

Each run clears the namespace first, so the index always matches the files exactly.
"""
import argparse
import json
import re
from datetime import date
from pathlib import Path

from pinecone import Pinecone

import config

HEADER_KEYS = {
    "Document ID": "doc_id",
    "Version": "version",
    "Updated": "updated_at",
    "Effective from": "effective_from",
    "Effective until": "effective_until",
    "Status": "status",
    "Tenant": "tenant_id",
    "Access roles": "acl_roles",
    "Document type": "doc_type",
}
OPEN_ENDED = 99991231  # effective_until for documents with no end date
BATCH_SIZE = 96  # Pinecone's limit per upsert_records call with integrated embedding


def date_to_int(value: str) -> int:
    """2026-10-01 -> 20261001, so Pinecone can filter dates with $lte / $gte."""
    return int(date.fromisoformat(value).strftime("%Y%m%d"))


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_document(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    """Return (document metadata, [(heading, section text), ...])."""
    text = path.read_text(encoding="utf-8")
    title = re.search(r"^# (.+)$", text, flags=re.M).group(1).strip()

    meta = {"title": title}
    for line in text.split("\n## ", 1)[0].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in HEADER_KEYS:
            meta[HEADER_KEYS[key.strip()]] = value.strip()

    missing = {"doc_id", "version", "status", "tenant_id", "acl_roles"} - meta.keys()
    if missing:
        raise ValueError(f"{path.name}: missing header fields {sorted(missing)}")

    meta["acl_roles"] = [r.strip() for r in meta["acl_roles"].split(",") if r.strip()]
    meta["effective_from"] = date_to_int(meta.get("effective_from") or meta["updated_at"])
    meta["effective_until"] = date_to_int(meta["effective_until"]) if "effective_until" in meta else OPEN_ENDED
    meta.setdefault("doc_type", "policy")

    parts = re.split(r"^## (.+)$", text, flags=re.M)
    sections = [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts), 2)]
    return meta, sections


def split_long(text: str) -> list[str]:
    """Split a section into overlapping word windows if it exceeds MAX_CHUNK_WORDS."""
    words = text.split()
    if len(words) <= config.MAX_CHUNK_WORDS:
        return [text]
    step = config.MAX_CHUNK_WORDS - config.OVERLAP_WORDS
    return [" ".join(words[i:i + config.MAX_CHUNK_WORDS]) for i in range(0, len(words) - config.OVERLAP_WORDS, step)]


def build_chunks(paths: list[Path]) -> list[dict]:
    chunks = []
    for path in paths:
        meta, sections = parse_document(path)
        for heading, body in sections:
            pieces = split_long(body)
            for n, piece in enumerate(pieces, start=1):
                chunk_id = f"{path.stem}#{slugify(heading)}" + (f"-{n}" if len(pieces) > 1 else "")
                chunks.append({
                    "_id": chunk_id,
                    # The title and heading go into the embedded text so a section keeps its context.
                    config.TEXT_FIELD: f"{meta['title']} > {heading}\n\n{piece}",
                    "heading": heading,
                    "source_uri": path.relative_to(config.PROJECT_DIR).as_posix(),
                    "parent_doc_id": meta["doc_id"],
                    **{k: v for k, v in meta.items() if k != "doc_id"},
                })
    ids = [c["_id"] for c in chunks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Duplicate chunk IDs: {sorted(duplicates)}")
    return chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--include-expired", action="store_true", help="also index negative_examples/*.md")
    parser.add_argument("--dry-run", action="store_true", help="parse and chunk only")
    args = parser.parse_args()

    paths = sorted(config.DATA_DIR.glob("*.md"))
    if args.include_expired:
        paths += sorted(config.EXPIRED_DIR.glob("*.md"))
    chunks = build_chunks(paths)

    print(f"{len(paths)} documents -> {len(chunks)} chunks")
    for c in chunks:
        words = len(c[config.TEXT_FIELD].split())
        print(f"  {c['_id']:<50} {words:>4} words  {c['status']:<8} {','.join(c['acl_roles'])}")

    config.CHUNKS_FILE.parent.mkdir(exist_ok=True)
    with config.CHUNKS_FILE.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"Wrote {config.CHUNKS_FILE.relative_to(config.PROJECT_DIR)}")

    if args.dry_run:
        return

    index = Pinecone().Index(name=config.INDEX_NAME)
    namespaces = {ns.name for page in index.list_namespaces() for ns in page.namespaces}  # SDK v10 yields pages
    if config.NAMESPACE in namespaces:
        index.delete(delete_all=True, namespace=config.NAMESPACE)
        print(f"Cleared namespace {config.NAMESPACE!r}")
    for i in range(0, len(chunks), BATCH_SIZE):
        index.upsert_records(records=chunks[i:i + BATCH_SIZE], namespace=config.NAMESPACE)
    print(f"Uploaded {len(chunks)} chunks to {config.INDEX_NAME}/{config.NAMESPACE}")


if __name__ == "__main__":
    main()
