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

        type_match = re.search(r"\*\*Type:\*\*\s*(\w+)", raw)
        entry_type = type_match.group(1) if type_match else None

        repo_match = re.search(r"\*\*Repo:\*\*\s*(\S+)", raw)
        entry_repo = repo_match.group(1) if repo_match else None

        entry_tags = re.findall(r"#([\w-]+)", raw)

        connections = []
        conn_match = re.search(r"\*\*Connections:\*\*(.+?)(?=\n\*\*|\n##|\Z)", raw, re.DOTALL)
        if conn_match:
            for line in conn_match.group(1).strip().split("\n"):
                line = line.strip().lstrip("- ")
                if line:
                    connections.append(line)

        entries.append({
            "id": entry_id,
            "date": date,
            "summary": summary,
            "file": str(filepath),
            "content": raw,
            "type": entry_type,
            "repo": entry_repo,
            "tags": entry_tags,
            "connections": connections,
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


def _build_metadata(entry: dict) -> dict:
    """Build ChromaDB metadata dict from a parsed entry."""
    meta = {
        "date": entry["date"],
        "summary": entry["summary"],
        "file": entry["file"],
    }
    if entry.get("type"):
        meta["type"] = entry["type"]
    if entry.get("repo"):
        meta["repo"] = entry["repo"]
    if entry.get("tags"):
        meta["tags"] = ",".join(entry["tags"])
    return meta


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
    metadatas = [_build_metadata(e) for e in all_entries]

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
    metadatas = [_build_metadata(e) for e in entries]

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    stored = collection.get(ids=ids)
    if len(stored["ids"]) != len(ids):
        print(f"Verification failed: expected {len(ids)} entries, found {len(stored['ids'])} in store.", file=sys.stderr)
        sys.exit(1)

    for entry in entries:
        print(f"Indexed: [{entry['date']}] {entry['summary']}")


def expand_connections(top_entries: list[dict], all_entries: list[dict],
                       max_hops: int = 2, max_additions: int = 10) -> list[dict]:
    """Follow Connections references from top entries to find related entries.

    Matches connection lines against all_entries by date + summary substring.
    Returns additional entries not already in top_entries, up to max_additions.
    """
    top_ids = {e["id"] for e in top_entries}
    seen = set(top_ids)
    additions = []

    frontier = list(top_entries)
    for hop in range(max_hops):
        next_frontier = []
        for entry in frontier:
            for conn_line in entry.get("connections", []):
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", conn_line)
                if not date_match:
                    continue
                conn_date = date_match.group(1)
                rest = conn_line[date_match.end():].strip().lstrip("—-– ").strip()

                for candidate in all_entries:
                    if candidate["id"] in seen:
                        continue
                    if candidate["date"] != conn_date:
                        continue
                    if rest and rest.lower()[:30] in candidate["summary"].lower():
                        seen.add(candidate["id"])
                        additions.append(candidate)
                        next_frontier.append(candidate)
                        if len(additions) >= max_additions:
                            return additions
        frontier = next_frontier
        if not frontier:
            break
    return additions


def boost_results(results: dict, repo: str = None, tags: list = None, entry_type: str = None) -> dict:
    """Re-rank vector search results by applying metadata score boosts.

    Boost factors: repo match +0.15, tag overlap +0.05/tag (max +0.15), type match +0.05.
    Modifies distances in-place and re-sorts all parallel arrays.
    """
    if not results["ids"][0]:
        return results

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = list(results["distances"][0])

    for i, metadata in enumerate(metadatas):
        boost = 0.0
        if repo and metadata.get("repo", "").lower() == repo.lower():
            boost += 0.15
        if tags and metadata.get("tags"):
            stored_tags = set(metadata["tags"].split(","))
            overlap = len(stored_tags & set(tags))
            boost += min(overlap * 0.05, 0.15)
        if entry_type and metadata.get("type", "").lower() == entry_type.lower():
            boost += 0.05
        distances[i] = max(0, distances[i] - boost)

    indices = sorted(range(len(ids)), key=lambda i: distances[i])
    results["ids"][0] = [ids[i] for i in indices]
    results["documents"][0] = [documents[i] for i in indices]
    results["metadatas"][0] = [metadatas[i] for i in indices]
    results["distances"][0] = [distances[i] for i in indices]
    return results


def format_tiered(entries: list[dict], top_full: int = 5, mid_summary: int = 10) -> str:
    """Format a ranked list of entries into three tiers.

    Tier 1 (top_full): full content.
    Tier 2 (mid_summary): key-idea + connections + patterns-emerging.
    Tier 3 (remainder): one-line summaries.
    """
    lines = []
    for i, entry in enumerate(entries):
        score_str = f" (score: {entry.get('score', 0):.2f})" if "score" in entry else ""
        if i < top_full:
            lines.append(f"\n{'='*60}")
            lines.append(f"[{i+1}] {entry['date']} — {entry['summary']}{score_str}")
            lines.append(f"{'='*60}")
            for line in entry["content"].strip().split("\n"):
                lines.append(f"  {line}")
        elif i < top_full + mid_summary:
            lines.append(f"\n--- [{entry['date']}] {entry['summary']}{score_str} ---")
            content = entry["content"]
            for section_label in ["Key idea", "Connections", "Patterns emerging"]:
                pattern = rf"\*\*{section_label}:\*\*(.+?)(?=\n\*\*|\n##|\Z)"
                match = re.search(pattern, content, re.DOTALL)
                if match:
                    text = match.group(1).strip()
                    lines.append(f"  **{section_label}:** {text[:200]}")
            if not any(re.search(rf"\*\*{s}:\*\*", content) for s in ["Key idea", "Connections", "Patterns emerging"]):
                content_lines = content.strip().split("\n")
                for line in content_lines[1:4]:
                    lines.append(f"  {line.strip()}")
        else:
            lines.append(f"  [{entry['date']}] {entry['summary']}")

    return "\n".join(lines)


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

    if getattr(args, "tiered", False):
        entries = []
        for doc_id, document, metadata, distance in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            entries.append({
                "date": metadata["date"],
                "summary": metadata["summary"],
                "content": document,
                "score": max(0, 1 - distance),
            })
        print(format_tiered(entries))
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


def _rank_by_keyword(entries: list[dict], keyword: str) -> list[dict]:
    """Rank entries by keyword frequency for the ripgrep fallback path."""
    keyword_lower = keyword.lower()
    for entry in entries:
        content_lower = entry["content"].lower()
        entry["_kw_score"] = content_lower.count(keyword_lower) * 0.1
    return sorted(entries, key=lambda e: e["_kw_score"], reverse=True)


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
                results = boost_results(results, repo=repo)

                scored_entries = []
                for doc_id, doc, metadata, distance in zip(
                    results["ids"][0],
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                ):
                    score = max(0, 1 - distance)
                    if score >= 0.3:
                        entry_data = {
                            "id": doc_id,
                            "date": metadata["date"],
                            "summary": metadata["summary"],
                            "content": doc,
                            "score": score,
                            "connections": [],
                        }
                        conn_match = re.search(
                            r"\*\*Connections:\*\*(.+?)(?=\n\*\*|\n##|\Z)",
                            doc, re.DOTALL,
                        )
                        if conn_match:
                            for line in conn_match.group(1).strip().split("\n"):
                                line = line.strip().lstrip("- ")
                                if line:
                                    entry_data["connections"].append(line)
                        scored_entries.append(entry_data)

                if scored_entries:
                    hop_additions = expand_connections(
                        scored_entries, all_entries, max_hops=2, max_additions=10
                    )
                    for add_entry in hop_additions:
                        scored_entries.append({
                            "date": add_entry["date"],
                            "summary": add_entry["summary"],
                            "content": add_entry["content"],
                            "score": 0.25,
                            "connections": add_entry.get("connections", []),
                        })

                    print(format_tiered(scored_entries))
                    return
        except Exception:
            pass

    repo_entries = [e for e in all_entries if repo.lower() in e["content"].lower()]
    if not repo_entries:
        repo_entries = all_entries[-top:]

    ranked = _rank_by_keyword(repo_entries, repo)[:top]
    tiered_entries = []
    for entry in ranked:
        tiered_entries.append({
            "date": entry["date"],
            "summary": entry["summary"],
            "content": entry["content"],
            "score": entry.get("_kw_score", 0),
        })
    print(format_tiered(tiered_entries))


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
    query_parser.add_argument("--tiered", action="store_true", help="Use tiered output format")

    subparsers.add_parser("summary", help="Overview of what's stored in the journal")

    recall_parser = subparsers.add_parser("auto-recall", help="Recall patterns for a repo")
    recall_parser.add_argument("repo", help="Repository name")
    recall_parser.add_argument("--top", type=int, default=20, help="Number of results")

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
