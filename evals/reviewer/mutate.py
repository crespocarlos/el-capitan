#!/usr/bin/env python3
"""Create deterministic reviewer mutation fixtures from a diff."""
import argparse,json,sys
p=argparse.ArgumentParser();p.add_argument('diff');a=p.parse_args(); text=open(a.diff).read()
mutations=[('removed null guard','if (value) {',''),('swallowed error','throw error;','return;'),('inverted condition','if (','if (!'),('dropped await','await ','')]
fixtures=[]
for name,old,new in mutations:
 fixtures.append({'mutation':name,'diff':text.replace(old,new,1) if old in text else text,'expected_findings':[name]})
print(json.dumps(fixtures,indent=2))
