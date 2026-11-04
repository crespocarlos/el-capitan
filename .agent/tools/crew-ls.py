#!/usr/bin/env python3
"""List crew task state without failing on malformed task metadata.

(default)    table of open specs, then a count of done specs; --all lists done specs; --md prints
             a Markdown table; --tsv prints the machine format (slug, branch, status, verdict, age).
--reconcile  report IMPLEMENTING specs ready to open a PR (all criteria checked, review pass or warn),
             stalled IMPLEMENTING specs, and idle DRAFTING/APPROVED specs (>14d).
--apply      with --reconcile, write ON-HOLD (naming the prior status) for idle specs and log to
             PROGRESS.md. Never sets DONE (crew open pr does, via --mark-done), ABANDONED or approval.
--mark-implementing TASK_DIR   set IMPLEMENTING when crew implement starts; only from APPROVED.
--mark-done TASK_DIR --pr-url URL [--branch NAME] [--force]
             set DONE from crew open pr; only from IMPLEMENTING, with all criteria checked, a review
             pass or warn, and --branch matching the task's branch. --force skips those evidence checks.
Rules live in transitions.json and are tried in file order; the first match wins.
"""
import argparse
import json,os,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

PREDICATES = {
 'all_checked': lambda r,rules: r['open']==0,
 'has_checkboxes': lambda r,rules: r['done']>0,
 'verdict_ok': lambda r,rules: r['verdict'].lower() in ('pass','warn'),
 'idle': lambda r,rules: r['age']>rules['idle_days'],
}
KINDS = ('ready','stalled','hold')
SAMPLE_FIELDS = dict(idle_days=0,prior='X',from_state='X')

def load_rules():
 path=Path(__file__).resolve().parent/'transitions.json'
 try:
  rules=json.loads(path.read_text())
  if not isinstance(rules['idle_days'],int): raise ValueError('idle_days must be an integer')
  for i,rule in enumerate(rules['auto']):
   where=f'auto[{i}]'
   for key in ('from','when','kind'):
    if key not in rule: raise ValueError(f'{where}: missing "{key}"')
   if rule['kind'] not in KINDS: raise ValueError(f'{where}: kind must be one of {KINDS}')
   unknown=[p for p in rule['when'] if p not in PREDICATES]
   if unknown: raise ValueError(f'{where}: unknown predicate {unknown}')
   if rule['kind']=='hold':
    for key in ('status','log'):
     if key not in rule: raise ValueError(f'{where}: hold rule needs "{key}"')
     rule[key].format(**SAMPLE_FIELDS)
 except (OSError,ValueError,KeyError,IndexError,TypeError,AttributeError) as error:
  print(f'error: {path.name}: {type(error).__name__}: {error}',file=sys.stderr)
  sys.exit(2)
 return rules
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

def decide(r,rules):
 for rule in rules['auto']:
  if head(r) in rule['from'] and all(PREDICATES[p](r,rules) for p in rule['when']):
   return rule
 return None

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
 unreviewed=sum(1 for r in done_rows if r['verdict'].lower() not in ('pass','warn'))
 print()
 print(f"{len(rows)} tasks: {len(open_rows)} open, {len(done_rows)} done"+('' if show_done else f" ({unreviewed} without a review pass; --all lists them)"))

def load_task(task_dir):
 if not (Path(task_dir)/'SPEC.md').is_file():
  print(f'error: no SPEC.md in {task_dir}',file=sys.stderr)
  return None
 return load(Path(task_dir))

def mark_implementing(task_dir):
 r=load_task(task_dir)
 if r is None: return 1
 if head(r)=='IMPLEMENTING':
  print(f'already implementing: {name(r)}')
  return 0
 if head(r)!='APPROVED':
  print(f"error: {name(r)} is {head(r) or 'unset'}, not APPROVED; nothing written",file=sys.stderr)
  return 1
 return 0 if set_status(r,'IMPLEMENTING','APPROVED → IMPLEMENTING') else 1

def mark_done(task_dir,pr_url,branch,force):
 r=load_task(task_dir)
 if r is None: return 1
 if head(r)=='DONE':
  print(f'already done: {name(r)}')
  return 0
 if head(r)!='IMPLEMENTING':
  print(f"error: {name(r)} is {head(r) or 'unset'}, not IMPLEMENTING; nothing written",file=sys.stderr)
  return 1
 problems=[]
 task_branch=r['meta'].get('branch')
 if branch and task_branch and branch!=task_branch:
  problems.append(f'task branch is {task_branch}, current branch is {branch}')
 if not (PREDICATES['all_checked'](r,None) and PREDICATES['has_checkboxes'](r,None)):
  problems.append(f"{r['open']} unchecked criteria/tasks" if r['open'] else 'no checked criteria')
 if not PREDICATES['verdict_ok'](r,None):
  problems.append(f"review verdict is {r['verdict']}, need pass or warn")
 if problems and not force:
  print(f"error: {name(r)}: {'; '.join(problems)}; nothing written (--force overrides)",file=sys.stderr)
  return 1
 return 0 if set_status(r,'done',f"IMPLEMENTING → DONE (PR opened: {pr_url})") else 1

def main():
 parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
 parser.add_argument("--tasks-dir",type=Path,default=Path.home()/".agent/tasks")
 parser.add_argument("--tsv",action="store_true",help="tab-separated slug, branch, status, verdict, age")
 parser.add_argument("--md",action="store_true",help="Markdown table, for pasting into chat")
 parser.add_argument("--all",action="store_true",help="list done specs too")
 parser.add_argument("--reconcile",action="store_true")
 parser.add_argument("--apply",action="store_true")
 parser.add_argument("--mark-implementing",metavar="TASK_DIR",help="set IMPLEMENTING when crew implement starts")
 parser.add_argument("--mark-done",metavar="TASK_DIR",help="set DONE after crew open pr; needs --pr-url")
 parser.add_argument("--pr-url")
 parser.add_argument("--branch",help="current branch; must match the task's branch")
 parser.add_argument("--force",action="store_true",help="skip the evidence checks in --mark-done")
 args=parser.parse_args()
 if args.mark_implementing:
  sys.exit(mark_implementing(args.mark_implementing))
 if args.mark_done:
  if not args.pr_url: parser.error("--mark-done requires --pr-url")
  sys.exit(mark_done(args.mark_done,args.pr_url,args.branch,args.force))
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
 rules=load_rules()
 decisions=[]
 for r in rows:
  rule=decide(r,rules)
  if rule: decisions.append((r,rule))
 of_kind=lambda kind:[r for r,rule in decisions if rule['kind']==kind]
 unreviewed=[r for r in rows if head(r)=='DONE' and r['verdict'].lower() not in ('pass','warn')]
 print('ready to open PR (all criteria checked, review pass or warn):')
 for r in of_kind('ready'): print(f"  {name(r)}\tstatus={r['status']}\tchecked={r['done']}")
 print(f"stalled IMPLEMENTING (>{rules['idle_days']}d, flagged only):")
 for r in of_kind('stalled'): print(f"  {name(r)}\t{r['age']}d")
 print('done without review pass (flagged only):')
 for r in unreviewed: print(f"  {name(r)}\tverdict={r['verdict']}")
 print(f"idle DRAFTING/APPROVED (>{rules['idle_days']}d -> ON-HOLD):")
 for r in of_kind('hold'): print(f"  {name(r)}\tstatus={r['status']}\t{r['age']}d")
 if args.apply:
  for r,rule in decisions:
   if rule['kind']!='hold': continue
   fields=dict(idle_days=rules['idle_days'],prior=head(r),from_state=head(r))
   set_status(r,rule['status'].format(**fields),rule['log'].format(**fields))

if __name__=="__main__": main()
