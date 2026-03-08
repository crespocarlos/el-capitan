#!/usr/bin/env python3
"""
journal-search — semantic search over el-capitan journal entries.

Uses Ollama for local embeddings and ChromaDB for vector storage.
All data stays on your machine.

Usage:
    journal-search index                              # Index all entries
    journal-search add <file> --entry <date>          # Index a single entry
    journal-search query "<text>" [--top N]           # Search by meaning
    journal-search summary                            # Overview of what's stored
    journal-search auto-recall <repo> [--top N]       # Recall patterns for a repo
"""

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

JOURNAL_DIR = Path.home() / ".agent" / "journal"
VECTORSTORE_DIR = Path.home() / ".agent" / "vectorstore"
COLLECTION_NAME = "journal"
EMBEDDING_MODEL = os.environ.get("JOURNAL_EMBED_MODEL", "nomic-embed-text")


def parse_entries(filepath: Path) -> list[dict]:
    """Parse a monthly journal file into individual entries."""
    content = filepath.read_text()
    content = re.sub(r"^---\n", "", content)
    raw_entries = re.split(r"\n---\n", content)
    entries = []
    for raw in raw_entries:
        raw = raw.strip()
        if not raw or not raw.startswith("## "):
            continue
        header_match = re.match(r"## (\d{4}-\d{2}-\d{2}) — (.+)", raw)
        if not header_match:
            continue
        date = header_match.group(1)
        summary = header_match.group(2)
        slug = hashlib.md5(summary.encode()).hexdigest()[:8]
        entry_id = f"{filepath.stem}:{date}:{slug}"
        entries.append({
            "id": entry_id,
            "date": date,
            "summary": summary,
            "file": str(filepath),
            "content": raw,
        })
    return entries


def get_collection():
    """Get or create the ChromaDB collection with Ollama embeddings."""
    try:
        import chromadb
    except ImportError:
        print("chromadb not installed. Run: pip install chromadb", file=sys.stderr)
        sys.exit(1)

    try:
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
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


def cmd_index(args):
    """Index all journal entries."""
    if not JOURNAL_DIR.exists():
        print(f"No journal directory at {JOURNAL_DIR}", file=sys.stderr)
        sys.exit(1)

    files = sorted(JOURNAL_DIR.glob("*.md"))
    if not files:
        print("No journal files found.", file=sys.stderr)
        sys.exit(1)

    all_entries = []
    for f in files:
        all_entries.extend(parse_entries(f))

    if not all_entries:
        print("No entries found in journal files.", file=sys.stderr)
        sys.exit(1)

    collection = get_collection()

    ids = [e["id"] for e in all_entries]
    documents = [e["content"] for e in all_entries]
    metadatas = [{"date": e["date"], "summary": e["summary"], "file": e["file"]} for e in all_entries]

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    print(f"Indexed {len(all_entries)} entries from {len(files)} files.")


def cmd_add(args):
    """Index a single entry from a journal file."""
    filepath = Path(args.file)
    if not filepath.exists():
        print(f"File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    entries = parse_entries(filepath)
    if args.entry:
        entries = [e for e in entries if e["date"] == args.entry]

    if not entries:
        print(f"No entries found matching date {args.entry} in {filepath}", file=sys.stderr)
        sys.exit(1)

    collection = get_collection()

    ids = [e["id"] for e in entries]
    documents = [e["content"] for e in entries]
    metadatas = [{"date": e["date"], "summary": e["summary"], "file": e["file"]} for e in entries]

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    stored = collection.get(ids=ids)
    if len(stored["ids"]) != len(ids):
        print(f"Verification failed: expected {len(ids)} entries, found {len(stored['ids'])} in store.", file=sys.stderr)
        sys.exit(1)

    for entry in entries:
        print(f"Indexed: [{entry['date']}] {entry['summary']}")


def cmd_query(args):
    """Search journal entries by semantic similarity."""
    collection = get_collection()

    results = collection.query(
        query_texts=[args.text],
        n_results=args.top,
    )

    if not results["ids"][0]:
        print("No matching entries found.")
        return

    for i, (doc_id, document, metadata, distance) in enumerate(zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )):
        score = max(0, 1 - distance)
        print(f"\n{'='*60}")
        print(f"[{i+1}] {metadata['date']} — {metadata['summary']}")
        print(f"    Score: {score:.2f} | File: {metadata['file']}")
        print(f"{'='*60}")
        lines = document.strip().split("\n")
        for line in lines[:15]:
            print(f"  {line}")
        if len(lines) > 15:
            print(f"  ... ({len(lines) - 15} more lines)")


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

    types = {}
    tags = {}
    repos = {}
    dates = []

    for entry in all_entries:
        dates.append(entry["date"])
        content = entry["content"]

        type_match = re.search(r"\*\*Type:\*\*\s*(\w+)", content)
        if type_match:
            t = type_match.group(1)
            types[t] = types.get(t, 0) + 1

        for tag in re.findall(r"#([\w-]+)", content):
            tags[tag] = tags.get(tag, 0) + 1

        repo_match = re.search(r"\*\*Repo:\*\*\s*(\S+)", content)
        if repo_match:
            r = repo_match.group(1)
            repos[r] = repos.get(r, 0) + 1

    print(f"Journal: {len(all_entries)} entries across {len(files)} files")
    print(f"Date range: {min(dates)} to {max(dates)}")
    print()

    if types:
        print("By type:")
        for t, count in sorted(types.items(), key=lambda x: -x[1]):
            print(f"  {t}: {count}")
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
        print(f"  [{entry['date']}] {entry['summary']}")


def cmd_auto_recall(args):
    """Recall patterns and conventions for a specific repo."""
    repo = args.repo
    top = args.top

    all_entries = []
    if JOURNAL_DIR.exists():
        for f in sorted(JOURNAL_DIR.glob("*.md")):
            all_entries.extend(parse_entries(f))

    if not all_entries:
        print("No journal entries found.", file=sys.stderr)
        sys.exit(1)

    has_chromadb = False
    try:
        import chromadb  # noqa: F401
        has_chromadb = True
    except ImportError:
        pass

    if has_chromadb:
        try:
            collection = get_collection()
            results = collection.query(
                query_texts=[f"patterns and conventions for {repo}"],
                n_results=top,
            )
            if results["ids"][0]:
                for doc, metadata, distance in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                ):
                    score = max(0, 1 - distance)
                    if score >= 0.3:
                        print(f"\n--- [{metadata['date']}] {metadata['summary']} (score: {score:.2f}) ---")
                        lines = doc.strip().split("\n")
                        for line in lines[:20]:
                            print(line)
                        if len(lines) > 20:
                            print(f"... ({len(lines) - 20} more lines)")
                return
        except Exception:
            pass

    repo_entries = [e for e in all_entries if repo.lower() in e["content"].lower()]
    if not repo_entries:
        repo_entries = all_entries[-top:]

    for entry in repo_entries[:top]:
        print(f"\n--- [{entry['date']}] {entry['summary']} ---")
        lines = entry["content"].strip().split("\n")
        for line in lines[:20]:
            print(line)
        if len(lines) > 20:
            print(f"... ({len(lines) - 20} more lines)")


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

    subparsers.add_parser("summary", help="Overview of what's stored in the journal")

    recall_parser = subparsers.add_parser("auto-recall", help="Recall patterns for a repo")
    recall_parser.add_argument("repo", help="Repository name")
    recall_parser.add_argument("--top", type=int, default=5, help="Number of results")

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
        cmd_auto_recall(args)


if __name__ == "__main__":
    main()
