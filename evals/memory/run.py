#!/usr/bin/env python3
"""Run deterministic persistent-memory retrieval checks."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEM = ROOT.parent.parent / '.agent' / 'bin' / 'mem.py'

def command(memory_dir, *arguments, journal_dir=None, input=None):
    env = {
        **os.environ, 'CREW_MEMORY_DIR': str(memory_dir),
        'PYTHONDONTWRITEBYTECODE': '1',
    }
    if journal_dir:
        env['CREW_JOURNAL_DIR'] = str(journal_dir)
    result = subprocess.run([sys.executable, str(MEM), *arguments], text=True,
        capture_output=True, env=env, input=input)
    return result

def run(memory_dir, *arguments, journal_dir=None):
    result = command(memory_dir, *arguments, journal_dir=journal_dir)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout)

def main():
    queries = json.loads((ROOT / 'queries.json').read_text())
    with tempfile.TemporaryDirectory() as temporary:
        store = Path(temporary) / 'store'
        journal = Path(temporary) / 'journal'; journal.mkdir()
        shutil.copytree(ROOT / 'fixtures' / 'store', store)
        initialized = command(store, 'init')
        if initialized.returncode:
            raise RuntimeError(initialized.stderr or initialized.stdout)
        source = journal / '2026-05.md'
        source.write_text("""---

## 2026-05-30 — Search migration evidence

The alpha search migration requires an explicit reindex after changing analyzers,
otherwise existing documents retain the previous token stream.

Review shard allocation before the reindex to avoid extending recovery.

**Tags:** #search #migration
**Repo:** acme-alpha

---

## 2026-05-31 — Global journal evidence

Keep raw journal evidence separate from durable memory until a candidate passes the
approval gate.

**Tags:** #memory

---
""")
        source_before = source.read_text()
        imported = command(store, 'journal', 'import', journal_dir=journal)
        if imported.returncode:
            raise RuntimeError(imported.stderr or imported.stdout)
        observation_ids = imported.stdout.split()
        source_unchanged_after_import = source.read_text() == source_before
        repeated_import = command(store, 'journal', 'import', journal_dir=journal)
        journal_added = command(
            store, 'journal', 'add', '--title', 'Journal add evidence',
            '--tags', 'memory', '--repo', 'acme-beta', '--date', '2026-05-31',
            journal_dir=journal, input='The journal add command records raw evidence.\n',
        )
        journal_add_id = journal_added.stdout.strip()
        journal_add_path = store / 'observations' / 'acme-beta' / f'{journal_add_id}.md'
        journal_add_content = (
            journal_add_path.read_text() if journal_add_path.exists() else ''
        )
        manual_observation = command(
            store, 'add', '--type', 'observation', '--scope', 'global',
            '--title', 'immutable observation', input='Manual raw evidence.\n',
        )
        archive_observation = command(store, 'archive', manual_observation.stdout.strip())
        traversal_add = command(
            store, 'journal', 'add', '--title', 'bad', '--tags', 'x', '--repo', '../escape',
            journal_dir=journal, input='x\n',
        )
        dry_run = command(store, 'journal', 'import', '--dry-run', journal_dir=journal)
        bad_journal = Path(journal) / '2026-06.md'
        bad_journal.write_text('## 2026-06-01 — Bad\n\n**Repo:** ../../escape\n\nbody\n\n---\n')
        traversal_import = command(store, 'journal', 'import', journal_dir=journal)
        bad_journal.unlink()
        type_search = run(store, 'search', 'raw', '--type', 'observation', '--json')
        default_search = run(store, 'search', 'analyzers', '--repo', 'acme-alpha', '--json')
        observation_search = run(
            store, 'search', 'analyzers', '--repo', 'acme-alpha',
            '--include-observations', '--json',
        )
        session = run(store, 'context', '--repo', 'acme-alpha', '--mode', 'session', '--json')
        session_with_observations = run(
            store, 'context', '--repo', 'acme-alpha', '--mode', 'session',
            '--include-observations', '--json',
        )
        observation_checks = {
            'journal_source_unchanged': source_unchanged_after_import,
            'journal_imported_paragraphs': len(observation_ids) == 3,
            'journal_reimport_idempotent': repeated_import.returncode == 0 and repeated_import.stdout.strip() == 'no changes',
            'journal_add_writes_direct_observation': (
                journal_added.returncode == 0
                and journal_add_id.startswith('observation-')
                and source.read_text() == source_before
                and 'title: "Journal add evidence"' in journal_add_content
                and 'created: 2026-05-31' in journal_add_content
                and 'keywords: ["memory"]' in journal_add_content
                and 'The journal add command records raw evidence.' in journal_add_content
            ),
            'observations_are_immutable': archive_observation.returncode == 1 and 'immutable' in archive_observation.stderr,
            'unsafe_scope_rejected': (
                traversal_add.returncode == 1 and traversal_import.returncode == 2
                and not (store / 'observations' / '..' / 'escape').exists()
                and not (store.parent / 'escape').exists()
            ),
            'journal_dry_run_writes_nothing': dry_run.returncode == 0 and dry_run.stdout.strip() == '',
            'type_observation_implies_include': len(type_search) >= 1,
            'search_excludes_observations': not default_search,
            'search_includes_observations': len(observation_search) == 1 and observation_search[0]['type'] == 'observation',
            'session_excludes_observations': not any(row['type'] == 'observation' for row in session),
            'session_includes_observations': any(row['type'] == 'observation' for row in session_with_observations),
        }
        hits = expected = correct_empty = empty_cases = superseded_leaks = scope_leaks = 0
        details = []
        for query in queries:
            returned = run(store, 'context', '--repo', query['repo'], '--mode', 'plan',
                           '--query', query['query'], '--json')
            ids = [entry['id'] for entry in returned]
            wanted = set(query['expected_ids'])
            hits += len(wanted & set(ids)); expected += len(wanted)
            if not wanted:
                empty_cases += 1; correct_empty += int(not ids)
            superseded_leaks += int('alpha-old' in ids)
            if query['kind'] == 'scope':
                scope_leaks += int(any(identifier.startswith('alpha-') for identifier in ids) and query['repo'] == 'acme-beta')
                scope_leaks += int(any(identifier.startswith('beta-') for identifier in ids) and query['repo'] == 'acme-alpha')
            details.append({**query, 'returned_ids': ids})
    scores = {'recall_at_5': hits / expected if expected else 1, 'correct_empty_rate': correct_empty / empty_cases if empty_cases else 1, 'superseded_leaks': superseded_leaks, 'cross_scope_leaks': scope_leaks, 'observation_checks': observation_checks, 'queries': details}
    results = ROOT / 'results'; results.mkdir(exist_ok=True)
    (results / f"{datetime.now().strftime('%Y%m%d%H%M%S')}.json").write_text(json.dumps(scores, indent=2) + '\n')
    print(json.dumps({key: value for key, value in scores.items() if key != 'queries'}, sort_keys=True))
    return 0 if scores['recall_at_5'] >= .8 and scores['correct_empty_rate'] >= .9 and not superseded_leaks and not scope_leaks and all(observation_checks.values()) else 1
if __name__ == '__main__':
    sys.exit(main())
