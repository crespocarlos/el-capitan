#!/usr/bin/env python3
import json,os,sys,tempfile
src,dst=sys.argv[1:]; a=json.load(open(src)); b=json.load(open(dst)) if os.path.exists(dst) else {'version':1,'hooks':{}}
h=b.setdefault('hooks',{})
for event, entries in a['hooks'].items():
 old=h.setdefault(event,[]); commands={x.get('command') for x in old}
 old.extend(x for x in entries if x.get('command') not in commands)
fd,tmp=tempfile.mkstemp(dir=os.path.dirname(dst),text=True)
with os.fdopen(fd,'w') as f: json.dump(b,f,indent=2);f.write('\n')
os.replace(tmp,dst)
