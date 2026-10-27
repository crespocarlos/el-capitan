#!/usr/bin/env python3
"""Report crew telemetry and task statistics."""
import argparse,json,subprocess,sys
from collections import Counter
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--since',default='7d');a=p.parse_args(); telemetry=Counter();invalid=0
for f in (Path.home()/'.agent').glob('**/*.jsonl'):
 for line in f.read_text(errors='ignore').splitlines():
  try:
   record=json.loads(line)
   if isinstance(record,dict): telemetry[record.get('tool','unknown')]+=1
   else: invalid+=1
  except json.JSONDecodeError: invalid+=1
print('telemetry',dict(telemetry));print('invalid telemetry',invalid);print('since',a.since)
subprocess.run([sys.executable,str(Path(__file__).with_name('mem.py')),'stats'],check=False)
