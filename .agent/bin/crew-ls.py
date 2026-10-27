#!/usr/bin/env python3
"""List crew task state without failing on malformed task metadata."""
import json,re,sys
from datetime import datetime,timezone
from pathlib import Path
for task in sorted((Path.home()/'.agent/tasks').glob('*')):
 spec=task/'SPEC.md'
 if not spec.exists(): continue
 try:
  text=spec.read_text()
  meta=json.loads((task/'.task-id').read_text()) if (task/'.task-id').exists() else {}
 except (OSError,json.JSONDecodeError) as error:
  print(f'warning: skipping {task.name}: {error}',file=sys.stderr)
  continue
 status=(re.search(r'## Status\s*\n([^\n]+)',text) or re.search(r'## Status:\s*([^\n]+)',text)); verdict=(re.search(r'Verdict:\s*(\w+)',(task/'REVIEW.md').read_text()) if (task/'REVIEW.md').exists() else None)
 age=int((datetime.now(timezone.utc).timestamp()-spec.stat().st_mtime)/86400)
 print('\t'.join([meta.get('slug',task.name),meta.get('branch','?'),status.group(1).strip() if status else '?',verdict.group(1) if verdict else '?',f'{age}d']))
