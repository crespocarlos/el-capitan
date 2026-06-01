#!/usr/bin/env python3
"""
journal-search — semantic search over el-capitan journal entries.

Uses Ollama for local embeddings and ChromaDB for vector storage.
All data stays on your machine.

Indexing strategy: each paragraph within an entry is indexed as a separate vector.
This gives precise retrieval — you get back the specific insight, not a 500-word
entry blob. Tags and repo travel as metadata on every paragraph.

Usage:
    journal-search index                              # Index all entries
    journal-search add <file> --entry <date>          # Index a single entry
    journal-search query "<text>" [--top N] [--distill]  # Search by meaning
    journal-search summary                            # Overview of what's stored
    journal-search auto-recall <repo> [--top N] [--distill]  # Recall for a repo
"""

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

JOURNAL_DIR = Path.home() / ".agent" / "journal"
VECTORSTORE_DIR = Path.home() / ".agent" / "vectorstore"
COLLECTION_NAME = "journal_v2"  # v2 = paragraph-level indexing
EMBEDDING_MODEL = os.environ.get("JOURNAL_EMBED_MODEL", "nomic-embed-text")
MIN_PARAGRAPH_WORDS = 8  # skip very short paragraphs (headers, etc.)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_entries(filepath: Path) -> list[dict]:
    """Parse a monthly journal file into individual entries."""
    content = filepath.read_text()
    # Strip leading separator if present
    content = re.sub(r"^---\n", "", content)
    # Split on explicit separators OR implicit date headers (handles missing --- between entries)
    raw_entries = re.split(r"\n---\n|\n(?=## \d{4}-\d{2}-\d{2} — )", content)
    entries = []
    for raw in raw_entries:
        raw = raw.strip()
        if not raw or not raw.startswith("## "):
            continue
        header_match = re.match(r"## (\d{4}-\d{2}-\d{2}) — (.+)", raw)
        if not header_match:
            continue
        date = header_match.group(1)
        title = header_match.group(2)
        slug = hashlib.md5(title.encode()).hexdigest()[:8]
        entry_id = f"{filepath.stem}:{date}:{slug}"

        repo_match = re.search(r"\*\*Repo:\*\*\s*(\S+)", raw)
        repo = repo_match.group(1) if repo_match else None

        tags_match = re.search(r"\*\*Tags:\*\*\s*(.+)", raw)
        tags = re.findall(r"#([\w-]+)", tags_match.group(1)) if tags_match else []

        entries.append({
            "id": entry_id,
            "date": date,
            "title": title,
            "file": str(filepath),
            "content": raw,
            "repo": repo,
            "tags": tags,
        })
    return entries


def extract_paragraphs(entry: dict) -> list[dict]:
    """Split an entry into indexable paragraphs.

    Each paragraph is one coherent idea. We split on blank lines, skip metadata
    lines (Tags, Repo, the header itself), and skip fragments that are too short
    to be meaningful.
    """
    content = entry["content"]
    # Remove ALL date header lines (handles merged entries from missing ---)
    content = re.sub(r"## \d{4}-\d{2}-\d{2} — .+\n?", "", content)
    # Remove metadata lines
    content = re.sub(r"\*\*Tags:\*\*.*\n?", "", content)
    content = re.sub(r"\*\*Repo:\*\*.*\n?", "", content)
    # Remove section headers (legacy ### Done, ### Absorbed etc.)
    content = re.sub(r"^### .+\n?", "", content, flags=re.MULTILINE)

    # Split on blank lines
    raw_paragraphs = re.split(r"\n{2,}", content)
    paragraphs = []
    for i, para in enumerate(raw_paragraphs):
        para = para.strip()
        if not para:
            continue
        # Skip if too short
        word_count = len(para.split())
        if word_count < MIN_PARAGRAPH_WORDS:
            continue
        # ID is content-hash only (stable across index/position shifts)
        para_hash = hashlib.md5(para.encode()).hexdigest()[:8]
        para_id = f"{entry['id']}:para:{para_hash}"
        paragraphs.append({
            "id": para_id,
            "text": para,
            "date": entry["date"],
            "title": entry["title"],
            "file": entry["file"],
            "repo": entry.get("repo") or "",
            "tags": ",".join(entry.get("tags", [])),
            "entry_id": entry["id"],  # for stale vector cleanup
        })
    return paragraphs


# ---------------------------------------------------------------------------
# ChromaDB
# ---------------------------------------------------------------------------

def get_collection():
    """Get or create the ChromaDB paragraph collection."""
    try:
        import chromadb  # type: ignore[import-untyped]
    except ImportError:
        print("chromadb not installed. Run: pip install chromadb", file=sys.stderr)
        sys.exit(1)
    try:
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction  # type: ignore[import-untyped]
    except ImportError:
        print("chromadb version too old. Run: pip install -U chromadb", file=sys.stderr)
        sys.exit(1)

    embedding_fn = OllamaEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        url="http://localhost:11434/api/embeddings",
    )
    client = chromadb.PersistentClient(path=str(VECTORSTORE_DIR))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )


def _upsert_paragraphs(paragraphs: list[dict]):
    """Upsert paragraphs, first deleting stale vectors for the same entries."""
    if not paragraphs:
        return 0
    collection = get_collection()

    # Upsert first — if this raises (OOM, embedding failure, disk full) the old
    # vectors are still intact and the journal stays queryable.
    collection.upsert(
        ids=[p["id"] for p in paragraphs],
        documents=[p["text"] for p in paragraphs],
        metadatas=[{
            "date": p["date"],
            "title": p["title"],
            "file": p["file"],
            "repo": p["repo"],
            "tags": p["tags"],
            "entry_id": p.get("entry_id", ""),
        } for p in paragraphs],
    )

    # Only after a successful upsert, delete stale paragraphs for these entries
    # so that edited/reordered paragraphs don't accumulate as orphan vectors.
    new_ids = {p["id"] for p in paragraphs}
    entry_ids = list({p["entry_id"] for p in paragraphs if p.get("entry_id")})
    for eid in entry_ids:
        try:
            existing = collection.get(where={"entry_id": eid})
            stale_ids = [i for i in existing["ids"] if i not in new_ids]
            if stale_ids:
                collection.delete(ids=stale_ids)
        except ValueError:
            pass  # empty collection — nothing to delete
        except Exception as exc:
            print(f"Warning: stale-vector cleanup failed for {eid}: {exc}",
                  file=sys.stderr)

    return len(paragraphs)


# ---------------------------------------------------------------------------
# Fallback text search (when Ollama/ChromaDB unavailable)
# ---------------------------------------------------------------------------

def _fallback_search(all_entries: list[dict], query: str, top: int) -> list[dict]:
    """Ripgrep-style keyword search when semantic search is unavailable."""
    query_words = query.lower().split()
    scored = []
    for entry in all_entries:
        for para in extract_paragraphs(entry):
            text_lower = para["text"].lower()
            score = sum(text_lower.count(w) for w in query_words)
            if score > 0:
                scored.append({**para, "score": score * 0.1})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top]


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_distill(paragraphs: list[dict], top: int = 10) -> str:
    """Return paragraphs as a flat list — one paragraph per item, most relevant first.

    This is the format for agent context injection: compact, high-signal, no noise.
    """
    lines = []
    for i, p in enumerate(paragraphs[:top]):
        lines.append(f"[{p['date']}] {p['title']}")
        lines.append(p["text"])
        lines.append("")
    return "\n".join(lines).strip()


def format_full(paragraphs: list[dict], top: int = 5) -> str:
    """Return paragraphs with score and metadata, for human inspection."""
    lines = []
    for i, p in enumerate(paragraphs[:top]):
        score_str = f" (score: {p.get('score', 0):.2f})" if "score" in p else ""
        lines.append(f"\n{'='*60}")
        lines.append(f"[{i+1}] {p['date']} — {p['title']}{score_str}")
        if p.get("repo"):
            lines.append(f"    Repo: {p['repo']} | Tags: {p['tags']}")
        lines.append(f"{'='*60}")
        lines.append(p["text"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_index(args):
    """Index all journal entries at paragraph level."""
    if not JOURNAL_DIR.exists():
        print(f"No journal directory at {JOURNAL_DIR}", file=sys.stderr)
        sys.exit(1)

    files = sorted(JOURNAL_DIR.glob("*.md"))
    if not files:
        print("No journal files found.", file=sys.stderr)
        sys.exit(1)

    all_paragraphs = []
    for f in files:
        for entry in parse_entries(f):
            all_paragraphs.extend(extract_paragraphs(entry))

    if not all_paragraphs:
        print("No paragraphs extracted from journal files.", file=sys.stderr)
        sys.exit(1)

    count = _upsert_paragraphs(all_paragraphs)
    print(f"Indexed {count} paragraphs from {len(files)} files.")


def cmd_add(args):
    """Index a single entry (or all entries from a file) at paragraph level."""
    filepath = Path(args.file)
    if not filepath.exists():
        print(f"File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    entries = parse_entries(filepath)
    if args.entry:
        entries = [e for e in entries if e["date"] == args.entry]

    if not entries:
        print(f"No entries matching date {args.entry} in {filepath}", file=sys.stderr)
        sys.exit(1)

    all_paragraphs = []
    for entry in entries:
        all_paragraphs.extend(extract_paragraphs(entry))

    if not all_paragraphs:
        print(f"No paragraphs extracted from {len(entries)} entries.", file=sys.stderr)
        sys.exit(1)

    count = _upsert_paragraphs(all_paragraphs)

    # Verify
    collection = get_collection()
    ids = [p["id"] for p in all_paragraphs]
    stored = collection.get(ids=ids)
    if len(stored["ids"]) != len(ids):
        print(f"Verification error: expected {len(ids)} paragraphs, "
              f"found {len(stored['ids'])} in store.", file=sys.stderr)
        sys.exit(1)

    for entry in entries:
        paras = extract_paragraphs(entry)
        print(f"Indexed: [{entry['date']}] {entry['title']} ({len(paras)} paragraphs)")


def _warn_if_empty_v2():
    """Print a one-line migration notice if journal_v2 is empty but journal v1 exists."""
    try:
        import chromadb  # type: ignore[import-untyped]
        client = chromadb.PersistentClient(path=str(VECTORSTORE_DIR))
        existing_names = [c.name for c in client.list_collections()]
        if "journal_v2" not in existing_names or \
                client.get_collection("journal_v2").count() == 0:
            v1_exists = "journal" in existing_names and \
                client.get_collection("journal").count() > 0
            hint = " (old 'journal' collection detected — run journal-search index to migrate)" \
                if v1_exists else " (run journal-search index to populate)"
            print(f"journal_v2 is empty{hint}", file=sys.stderr)
    except Exception:
        pass  # best-effort — don't block query on diagnostic failure


def cmd_query(args):
    """Search by semantic similarity. Returns paragraphs, not full entries."""
    top = args.top
    distill = getattr(args, "distill", False)
    repo = getattr(args, "repo", None)

    _warn_if_empty_v2()

    # Try semantic search
    try:
        collection = get_collection()
        where = {"repo": repo} if repo else None
        query_kwargs = dict(query_texts=[args.text], n_results=min(top * 2, 50))
        if where:
            query_kwargs["where"] = where
        results = collection.query(**query_kwargs)

        if results["ids"][0]:
            paragraphs = []
            for pid, doc, meta, dist in zip(
                results["ids"][0],
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                score = max(0, 1 - dist)
                # Boost repo match
                if repo and meta.get("repo", "").lower() == repo.lower():
                    score = min(1.0, score + 0.15)
                if score >= 0.25:
                    paragraphs.append({
                        "id": pid,
                        "text": doc,
                        "date": meta["date"],
                        "title": meta["title"],
                        "file": meta["file"],
                        "repo": meta.get("repo", ""),
                        "tags": meta.get("tags", ""),
                        "score": score,
                    })
            paragraphs.sort(key=lambda x: x["score"], reverse=True)
            paragraphs = paragraphs[:top]

            if distill:
                print(format_distill(paragraphs, top))
            else:
                print(format_full(paragraphs, top))
            return
    except Exception as e:
        print(f"Semantic search unavailable ({e}), falling back to text search.",
              file=sys.stderr)

    # Fallback: keyword search
    all_entries = []
    if JOURNAL_DIR.exists():
        for f in sorted(JOURNAL_DIR.glob("*.md")):
            all_entries.extend(parse_entries(f))
    paragraphs = _fallback_search(all_entries, args.text, top)
    if distill:
        print(format_distill(paragraphs, top))
    else:
        print(format_full(paragraphs, top))


def cmd_summary(args):
    """Print an overview of what's stored in the journal."""
    if not JOURNAL_DIR.exists():
        print(f"No journal directory at {JOURNAL_DIR}", file=sys.stderr)
        sys.exit(1)

    files = sorted(JOURNAL_DIR.glob("*.md"))
    if not files:
        print("No journal files found.")
        return

    all_entries = []
    for f in files:
        all_entries.extend(parse_entries(f))

    if not all_entries:
        print("No entries found.")
        return

    tags: dict = {}
    repos: dict = {}
    dates = []
    total_paragraphs = 0

    for entry in all_entries:
        dates.append(entry["date"])
        for tag in entry.get("tags", []):
            tags[tag] = tags.get(tag, 0) + 1
        if entry.get("repo"):
            r = entry["repo"]
            repos[r] = repos.get(r, 0) + 1
        total_paragraphs += len(extract_paragraphs(entry))

    print(f"Journal: {len(all_entries)} entries, ~{total_paragraphs} paragraphs, "
          f"across {len(files)} files")
    print(f"Date range: {min(dates)} to {max(dates)}")
    print()

    if repos:
        print("By repo:")
        for r, count in sorted(repos.items(), key=lambda x: -x[1]):
            print(f"  {r}: {count}")
        print()

    if tags:
        top_tags = sorted(tags.items(), key=lambda x: -x[1])[:15]
        print("Top tags:")
        for tag, count in top_tags:
            print(f"  #{tag}: {count}")
        print()

    print("Entries:")
    for entry in all_entries:
        paras = extract_paragraphs(entry)
        print(f"  [{entry['date']}] {entry['title']} ({len(paras)}p)")


def cmd_auto_recall(args):
    """Recall relevant paragraphs for a repo. Default output is distilled (prose paragraphs)."""
    repo = args.repo
    top = args.top
    distill = getattr(args, "distill", True)  # distill is on by default for auto-recall

    _warn_if_empty_v2()

    all_entries = []
    if JOURNAL_DIR.exists():
        for f in sorted(JOURNAL_DIR.glob("*.md")):
            all_entries.extend(parse_entries(f))

    if not all_entries:
        print("No journal entries found.", file=sys.stderr)
        sys.exit(1)

    # Try semantic search
    try:
        collection = get_collection()
        results = collection.query(
            query_texts=[f"patterns, lessons, and warnings for {repo}"],
            n_results=min(top * 3, 100),
        )

        if results["ids"][0]:
            paragraphs = []
            for pid, doc, meta, dist in zip(
                results["ids"][0],
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                score = max(0, 1 - dist)
                # Strong boost for repo match
                if meta.get("repo", "").lower() == repo.lower():
                    score = min(1.0, score + 0.2)
                if score >= 0.3:
                    paragraphs.append({
                        "id": pid,
                        "text": doc,
                        "date": meta["date"],
                        "title": meta["title"],
                        "file": meta["file"],
                        "repo": meta.get("repo", ""),
                        "tags": meta.get("tags", ""),
                        "score": score,
                    })
            paragraphs.sort(key=lambda x: x["score"], reverse=True)
            paragraphs = paragraphs[:top]

            if paragraphs:
                if distill:
                    print(format_distill(paragraphs, top))
                else:
                    print(format_full(paragraphs, top))
                return
    except Exception as e:
        print(f"Semantic search unavailable ({e}), falling back to text search.",
              file=sys.stderr)

    # Fallback: filter by repo name in content, rank by keyword frequency
    repo_entries = [e for e in all_entries if repo.lower() in e["content"].lower()]
    if not repo_entries:
        repo_entries = all_entries[-20:]

    all_paragraphs = []
    for entry in repo_entries:
        for para in extract_paragraphs(entry):
            score = para["text"].lower().count(repo.lower()) * 0.1
            all_paragraphs.append({**para, "score": score})

    all_paragraphs.sort(key=lambda x: x["score"], reverse=True)
    result = all_paragraphs[:top]

    if distill:
        print(format_distill(result, top))
    else:
        print(format_full(result, top))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Semantic search over journal entries")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("index", help="Index all journal entries")

    add_parser = subparsers.add_parser("add", help="Index a single entry")
    add_parser.add_argument("file", help="Path to the journal file")
    add_parser.add_argument("--entry", help="Date of the entry (YYYY-MM-DD)")

    query_parser = subparsers.add_parser("query", help="Search by semantic similarity")
    query_parser.add_argument("text", help="Search query")
    query_parser.add_argument("--top", type=int, default=5, help="Number of results")
    query_parser.add_argument("--distill", action="store_true",
                               help="Return plain prose paragraphs (best for agent context)")
    query_parser.add_argument("--repo", help="Boost results matching this repo")

    subparsers.add_parser("summary", help="Overview of what's stored in the journal")

    recall_parser = subparsers.add_parser("auto-recall", help="Recall for a repo")
    recall_parser.add_argument("repo", help="Repository name")
    recall_parser.add_argument("--top", type=int, default=10,
                                help="Number of paragraphs to return")
    recall_parser.add_argument("--no-distill", action="store_true",
                                help="Return full output with scores instead of prose")

    args = parser.parse_args()

    if args.command == "index":
        cmd_index(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "query":
        cmd_query(args)
    elif args.command == "summary":
        cmd_summary(args)
    elif args.command == "auto-recall":
        # distill is on by default; --no-distill turns it off
        args.distill = not args.no_distill
        cmd_auto_recall(args)


if __name__ == "__main__":
    main()
