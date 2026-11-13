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
             pass or warn, the reviewed commit as an ancestor of HEAD, and --branch matching the
             task's branch. --force is a user-invoked escape hatch that skips those evidence checks.
Rules live in transitions.json and are tried in file order; the first match wins.
"""
import argparse
import json,os,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

# Installed flat into ~/.agent/bin, but in the repo this file is .agent/tools and the
# shared status contract lives in .agent/scripts.
for _dir in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent/'scripts'):
    if (_dir/'task_status.py').is_file() and str(_dir) not in sys.path:
        sys.path.insert(0,str(_dir))
from task_status import STATUS, head as _head, read_status  # noqa: E402

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
# `## Status` contract lives in task_status.py; this module must not redefine it.
# A verdict is a bare word ending its clause; pass-with-nits or "pass | warn" do not count.
VERDICT = re.compile(r'^\s*(?:#+\s*)?(?:\*\*)?Verdict:?(?:\*\*)?\s*([A-Za-z]+)(?=[ \t]*(?:[.:;,]|$))', re.M)
# An unresolved clarification blocks implementation; one shown inside a fenced example
# (a spec template or docs snippet) does not.
UNRESOLVED = re.compile(r'\[NEEDS CLARIFICATION', re.M)
FENCED = re.compile(r'^```.*?^```', re.M | re.S)


def unresolved(spec_text):
 return bool(UNRESOLVED.search(FENCED.sub('', spec_text)))
ACTIVITY_FILES = ('SPEC.md','PROGRESS.md','REVIEW.md','REPORT.md')
LOG_PROGRESS = Path(__file__).resolve().parent/'log-progress.py'
CHECK_TYPED = Path(__file__).resolve().parent/'check-spec-typed-tests.py'


def typed_tests_problem(spec_path):
 """Return the checker's message when a typed ## Tests block has no runnable Command.

 Approval is when the tests section becomes a commitment, so this runs before Gate 1 is
 recorded. A spec with no ## Tests section passes: `crew test` reports WARN for it, which is
 a documented outcome, not an error.
 """
 if not CHECK_TYPED.is_file():
  return f"validator missing: {CHECK_TYPED}"
 try:
  r=subprocess.run([sys.executable,str(CHECK_TYPED),str(spec_path)],capture_output=True,text=True)
 except OSError as error:
  return f"validator could not run: {error}"
 if r.returncode==0: return ''
 detail=(r.stderr or r.stdout).strip().splitlines()
 return detail[-1] if detail else f"validator exited {r.returncode}"

def name(r):
 return r['meta'].get('slug',r['task'].name)

def head(r):
 return _head(r['status'])

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

def mark_approved(task_dir):
 """Gate 1: the user approved the spec. Only DRAFTING can be approved."""
 r=load_task(task_dir)
 if r is None: return 1
 if head(r)=='APPROVED':
  print(f'already approved: {name(r)}')
  return 0
 if head(r)!='DRAFTING':
  print(f"error: {name(r)} is {head(r) or 'unset'}, not DRAFTING; nothing written",file=sys.stderr)
  return 1
 if unresolved(r['text']):
  print(f"error: {name(r)} still has [NEEDS CLARIFICATION] items; a spec with open items cannot be approved",file=sys.stderr)
  return 1
 problem=typed_tests_problem(r['task']/'SPEC.md')
 if problem:
  print(f"error: {name(r)}: {problem}; fix the ## Tests block before approving",file=sys.stderr)
  return 1
 return 0 if set_status(r,'APPROVED','DRAFTING → APPROVED') else 1

def update_task_branch(r,branch):
 """Record the branch actually being implemented, keeping the drafting branch.

 `.task-id.branch` is the resolution key, so overwriting it strands the checkout the
 spec was written in. `spec_branch` holds the drafting branch and resolution matches
 either; writing metadata before SPEC.md means an interrupt cannot leave the status
 advanced with no branch recorded.
 """
 metadata_path=r['task']/'.task-id'
 tmp=metadata_path.with_name('.task-id.tmp')
 try:
  metadata=json.loads(metadata_path.read_text())
  if not isinstance(metadata,dict): raise ValueError('not an object')
  if metadata.get('branch')==branch: return True
  if metadata.get('spec_branch') in (None,''): metadata['spec_branch']=metadata.get('branch','')
  metadata['branch']=branch
  tmp.write_text(json.dumps(metadata,indent=2)+'\n')
  os.replace(tmp,metadata_path)
  return True
 except (OSError,ValueError) as error:
  tmp.unlink(missing_ok=True)
  print(f'error: {name(r)}: .task-id not updated: {error}',file=sys.stderr)
  return False

def mark_implementing(task_dir,branch=''):
 r=load_task(task_dir)
 if r is None: return 1
 if head(r)=='IMPLEMENTING':
  print(f'already implementing: {name(r)}')
  if branch: update_task_branch(r,branch)
  return 0
 if head(r)!='APPROVED':
  print(f"error: {name(r)} is {head(r) or 'unset'}, not APPROVED; nothing written",file=sys.stderr)
  return 1
 if unresolved(r['text']):
  print(f"error: {name(r)} still has [NEEDS CLARIFICATION] items; resolve them before implementing",file=sys.stderr)
  return 1
 # Record the implementing branch first: task resolution keys on it, and writing it
 # after the status would leave an interrupt with the status advanced and no branch.
 if branch and not update_task_branch(r,branch): return 1
 return 0 if set_status(r,'IMPLEMENTING','APPROVED → IMPLEMENTING') else 1

REVIEWED_AT = re.compile(r'^Reviewed at:\s*([0-9a-f]{7,40})\s*$', re.M)

def read_reviewed_at(task):
 review=task/'REVIEW.md'
 if not review.exists(): return ''
 matches=REVIEWED_AT.findall(review.read_text())
 return matches[-1] if matches else ''

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
 reviewed_at=read_reviewed_at(r['task'])
 if reviewed_at:
  # `crew commit` runs after `crew review`, so HEAD is normally one or more commits ahead
  # of the reviewed tree. Accept the reviewed commit as an ancestor; an unrelated or
  # unresolvable SHA must fail rather than silently satisfy the gate.
  ancestor=subprocess.run(['git','merge-base','--is-ancestor',reviewed_at,'HEAD'],capture_output=True)
  if ancestor.returncode==1:
   current=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
   problems.append(f'review was of {reviewed_at[:12]}, which is not an ancestor of HEAD {current[:12]}; re-run crew review')
  elif ancestor.returncode!=0:
   problems.append(f'cannot verify that review {reviewed_at[:12]} covers HEAD; run from the implementation checkout')
 elif branch:
  # Legacy reviews carry no identity; flag rather than block so old tasks still close.
  print('warning: REVIEW.md has no "Reviewed at:" commit; cannot confirm it covers HEAD',file=sys.stderr)
 if problems and not force:
  print(f"error: {name(r)}: {'; '.join(problems)}; nothing written (--force overrides)",file=sys.stderr)
  return 1
 return 0 if set_status(r,'DONE',f"IMPLEMENTING → DONE (PR opened: {pr_url})") else 1

def main():
 parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
 parser.add_argument("--tasks-dir",type=Path,default=Path.home()/".agent/tasks")
 parser.add_argument("--tsv",action="store_true",help="tab-separated slug, branch, status, verdict, age")
 parser.add_argument("--md",action="store_true",help="Markdown table, for pasting into chat")
 parser.add_argument("--all",action="store_true",help="list done specs too")
 parser.add_argument("--reconcile",action="store_true")
 parser.add_argument("--apply",action="store_true")
 parser.add_argument("--mark-approved",metavar="TASK_DIR",help="record Gate 1: set APPROVED from DRAFTING")
 parser.add_argument("--status-file",metavar="SPEC.md",help="print the Status value of one spec (single reader for hooks)")
 parser.add_argument("--mark-implementing",metavar="TASK_DIR",help="set IMPLEMENTING when crew implement starts")
 parser.add_argument("--mark-done",metavar="TASK_DIR",help="set DONE after crew open pr; needs --pr-url")
 parser.add_argument("--pr-url")
 parser.add_argument("--branch",help="current branch; must match the task's branch")
 parser.add_argument("--force",action="store_true",help="skip the evidence checks in --mark-done")
 args=parser.parse_args()
 if args.status_file:
  # Single source for the `## Status` contract: hooks and tools must not re-implement it.
  try:
   text=Path(args.status_file).read_text()
  except OSError as error:
   print(f'error: {error}',file=sys.stderr)
   sys.exit(1)
  match=STATUS.search(text)
  print(match.group(2).strip() if match else '')
  return 0
 if args.mark_approved:
  sys.exit(mark_approved(args.mark_approved))
 if args.mark_implementing:
  sys.exit(mark_implementing(args.mark_implementing,args.branch or ''))
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
  failed=[]
  for r,rule in decisions:
   if rule['kind']!='hold': continue
   fields=dict(idle_days=rules['idle_days'],prior=head(r),from_state=head(r))
   if not set_status(r,rule['status'].format(**fields),rule['log'].format(**fields)):
    failed.append(name(r))
  if failed:
   print(f'error: {len(failed)} spec(s) not updated: {", ".join(failed)}',file=sys.stderr)
   return 1

if __name__=="__main__": sys.exit(main() or 0)
