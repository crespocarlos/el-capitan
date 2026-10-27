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

def run(memory_dir, *arguments):
    result = subprocess.run([sys.executable, str(MEM), *arguments], text=True,
        capture_output=True, env={**os.environ, 'CREW_MEMORY_DIR': str(memory_dir), 'PYTHONDONTWRITEBYTECODE': '1'})
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout)

def main():
    queries = json.loads((ROOT / 'queries.json').read_text())
    with tempfile.TemporaryDirectory() as temporary:
        store = Path(temporary) / 'store'
        shutil.copytree(ROOT / 'fixtures' / 'store', store)
        subprocess.run([sys.executable, str(MEM), 'init'], check=True,
            env={**os.environ, 'CREW_MEMORY_DIR': str(store), 'PYTHONDONTWRITEBYTECODE': '1'})
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
    scores = {'recall_at_5': hits / expected if expected else 1, 'correct_empty_rate': correct_empty / empty_cases if empty_cases else 1, 'superseded_leaks': superseded_leaks, 'cross_scope_leaks': scope_leaks, 'queries': details}
    results = ROOT / 'results'; results.mkdir(exist_ok=True)
    (results / f"{datetime.now().strftime('%Y%m%d%H%M%S')}.json").write_text(json.dumps(scores, indent=2) + '\n')
    print(json.dumps({key: value for key, value in scores.items() if key != 'queries'}, sort_keys=True))
    return 0 if scores['recall_at_5'] >= .8 and scores['correct_empty_rate'] >= .9 and not superseded_leaks and not scope_leaks else 1
if __name__ == '__main__':
    sys.exit(main())
