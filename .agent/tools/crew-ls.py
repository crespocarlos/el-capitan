#!/usr/bin/env python3
"""List crew task state without failing on malformed task metadata.

(default)    table of open specs, then a count of done specs; --all lists done specs; --md prints
             a Markdown table; --tsv prints the machine format (slug, branch, status, verdict, age).
--reconcile  report status drift: DONE candidates (IMPLEMENTING/APPROVED, all checkboxes [x], last
             REVIEW.md verdict pass) and idle DRAFTING/APPROVED specs (>14d).
--apply      with --reconcile, write DONE for candidates and ON-HOLD (naming the prior status) for
             idle specs, and log each transition to PROGRESS.md. Never sets ABANDONED or approves.
"""
import argparse
import json,os,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

STALE_DAYS = 14
OPEN_ITEM = re.compile(r'^\s*[-*]\s\[ \]', re.M)
DONE_ITEM = re.compile(r'^\s*[-*]\s\[[xX]\]', re.M)
STATUS = re.compile(r'^(## Status[ \t]*\r?\n)([^\n#][^\n]*?)[ \t]*$', re.M)
# A verdict is a bare word ending its clause; pass-with-nits or "pass | warn" do not count.
VERDICT = re.compile(r'^\s*(?:#+\s*)?(?:\*\*)?Verdict:?(?:\*\*)?\s*([A-Za-z]+)(?=[ \t]*(?:[.:;,]|$))', re.M)
ACTIVITY_FILES = ('SPEC.md','PROGRESS.md','REVIEW.md','REPORT.md')
LOG_PROGRESS = Path(__file__).resolve().parent/'log-progress.py'

def name(r):
 return r['meta'].get('slug',r['task'].name)

def head(r):
 return r['status'].split()[0].upper().rstrip('(:') if r['status'] else ''

def load(task):
 spec=task/'SPEC.md'
 text=spec.read_text()
 meta=json.loads((task/'.task-id').read_text()) if (task/'.task-id').exists() else {}
 if not isinstance(meta,dict): meta={}
 status=STATUS.search(text)
 verdicts=VERDICT.findall((task/'REVIEW.md').read_text()) if (task/'REVIEW.md').exists() else []
 newest=max((task/f).stat().st_mtime for f in ACTIVITY_FILES if (task/f).exists())
 return dict(task=task,text=text,meta=meta,status=status.group(2).strip() if status else None,
  verdict=verdicts[-1] if verdicts else '?',age=int((datetime.now(timezone.utc).timestamp()-newest)/86400),
  open=len(OPEN_ITEM.findall(text)),done=len(DONE_ITEM.findall(text)))

def set_status(r,value,transition):
 spec=r['task']/'SPEC.md'
 tmp=spec.with_name('SPEC.md.tmp')
 try:
  current=spec.read_text()
  if current!=r['text']: raise OSError('SPEC.md changed since it was read')
  updated,count=STATUS.subn(lambda m: m.group(1)+value,current,count=1)
  if count!=1: raise OSError('no Status value found')
  tmp.write_text(updated)
  os.replace(tmp,spec)
 except OSError as error:
  tmp.unlink(missing_ok=True)
  print(f'error: {name(r)}: {error}',file=sys.stderr)
  return False
 logged=subprocess.run([sys.executable,str(LOG_PROGRESS),str(r['task']),transition],capture_output=True,text=True)
 if logged.returncode!=0: print(f'warning: {name(r)}: PROGRESS.md not updated: {logged.stderr.strip()}',file=sys.stderr)
 print(f"applied: {name(r)} -> {value.split()[0]}")
 return True

OPEN_ORDER = ['IMPLEMENTING','APPROVED','DRAFTING','ON-HOLD']

def state_label(r):
 if head(r)=='ON-HOLD':
  was=re.search(r'was ([A-Za-z-]+)',r['status'])
  return f'ON-HOLD (was {was.group(1)})' if was else 'ON-HOLD'
 return head(r) or '?'

def print_table(rows,show_done,markdown=False):
 def rank(r):
  return OPEN_ORDER.index(head(r)) if head(r) in OPEN_ORDER else len(OPEN_ORDER)
 open_rows=sorted([r for r in rows if head(r)!='DONE'],key=lambda r:(rank(r),r['age']))
 done_rows=sorted([r for r in rows if head(r)=='DONE'],key=lambda r:r['age'])
 shown=open_rows+(done_rows if show_done else [])
 cut=lambda text,width: text if len(text)<=width else text[:width-1]+'…'
 table=[('STATE','TASK','BRANCH','REVIEW','AGE')]+[
  (state_label(r),name(r) if markdown else cut(name(r),50),r['meta'].get('branch','-') if markdown else cut(r['meta'].get('branch','-'),32),r['verdict'].upper() if r['verdict']!='?' else '-','today' if r['age']==0 else f"{r['age']}d")
  for r in shown]
 if markdown:
  for n,row in enumerate(table):
   print('| '+' | '.join(cell.replace('|','\\|') for cell in row)+' |')
   if n==0: print('|'+'|'.join(['---']*5)+'|')
 else:
  widths=[max(len(row[i]) for row in table) for i in range(5)]
  for row in table:
   print('  '.join(cell.ljust(widths[i]) for i,cell in enumerate(row)).rstrip())
 unreviewed=sum(1 for r in done_rows if r['verdict'].lower()!='pass')
 print()
 print(f"{len(rows)} tasks: {len(open_rows)} open, {len(done_rows)} done"+('' if show_done else f" ({unreviewed} without a review pass; --all lists them)"))

def main():
 parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
 parser.add_argument("--tasks-dir",type=Path,default=Path.home()/".agent/tasks")
 parser.add_argument("--tsv",action="store_true",help="tab-separated slug, branch, status, verdict, age")
 parser.add_argument("--md",action="store_true",help="Markdown table, for pasting into chat")
 parser.add_argument("--all",action="store_true",help="list done specs too")
 parser.add_argument("--reconcile",action="store_true")
 parser.add_argument("--apply",action="store_true")
 args=parser.parse_args()
 if args.apply and not args.reconcile:
  parser.error("--apply requires --reconcile")
 rows=[]
 for task in sorted(args.tasks_dir.glob('*')):
  if not (task/'SPEC.md').exists(): continue
  try:
   rows.append(load(task))
  except (OSError,ValueError,AttributeError) as error:
   print(f'warning: skipping {task.name}: {error}',file=sys.stderr)
 if not args.reconcile:
  if args.tsv:
   for r in rows:
    print('\t'.join([name(r),r['meta'].get('branch','?'),r['status'] or '?',r['verdict'],f"{r['age']}d"]))
  else:
   print_table(rows,args.all,args.md)
  return
 candidates=[r for r in rows if head(r) in {'IMPLEMENTING','APPROVED'} and r['open']==0 and r['done']>0 and r['verdict'].lower()=='pass']
 idle=[r for r in rows if head(r) in {'DRAFTING','APPROVED'} and r['age']>STALE_DAYS and r not in candidates]
 unreviewed=[r for r in rows if head(r)=='DONE' and r['verdict'].lower()!='pass']
 print('done (all checkboxes [x] and review pass):')
 for r in candidates: print(f"  {name(r)}\tstatus={r['status']}\tchecked={r['done']}")
 print('done without review pass (flagged only):')
 for r in unreviewed: print(f"  {name(r)}\tverdict={r['verdict']}")
 print(f'idle DRAFTING/APPROVED (>{STALE_DAYS}d -> ON-HOLD):')
 for r in idle: print(f"  {name(r)}\tstatus={r['status']}\t{r['age']}d")
 if args.apply:
  for r in candidates:
   set_status(r,'done',f"{head(r)} → done (auto: all criteria checked, review pass)")
  for r in idle:
   prior=r['status'].split()[0]
   set_status(r,f"ON-HOLD (auto-hold: no activity {STALE_DAYS}d; was {prior})",f"{head(r)} → ON-HOLD (auto: idle {STALE_DAYS}d)")

if __name__=="__main__": main()
