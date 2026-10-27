#!/usr/bin/env python3
"""Inspect crew evaluation documents in Elasticsearch."""
import argparse, base64, collections, json, os, sys, urllib.error, urllib.request
URL=os.environ.get('ES_URL','http://localhost:9200').rstrip('/')
def search(index, query):
 h={'Content-Type':'application/json'}
 if os.environ.get('ES_API_KEY'): h['Authorization']='ApiKey '+os.environ['ES_API_KEY']
 elif os.environ.get('ES_USER'): h['Authorization']='Basic '+base64.b64encode(f"{os.environ['ES_USER']}:{os.environ.get('ES_PASS','')}".encode()).decode()
 try:
  r=urllib.request.Request(f'{URL}/{index}/_search',data=json.dumps(query).encode(),headers=h)
  with urllib.request.urlopen(r,timeout=5) as x:return json.load(x)
 except (urllib.error.URLError,urllib.error.HTTPError,TimeoutError) as e: print(f'Elasticsearch unavailable: {e}',file=sys.stderr);raise SystemExit(2)
def docs(exp=None,metric=None):
 must=[]
 if exp:must.append({'term':{'experiment_id':exp}})
 if metric:must.append({'term':{'evaluator.name':metric}})
 return [x['_source'] for x in search('.evaluation-scores*',{'size':500,'query':{'bool':{'must':must}}})['hits']['hits']]
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
 s.add_parser('latest');x=s.add_parser('scores');x.add_argument('exp');x=s.add_parser('failures');x.add_argument('exp');x.add_argument('--metric');x=s.add_parser('trace');x.add_argument('exp');x.add_argument('example');x.add_argument('--metric');s.add_parser('ki');x=s.add_parser('flips');x.add_argument('expA');x.add_argument('expB');x=s.add_parser('cluster');x.add_argument('exp',nargs='+');a=p.parse_args()
 if a.cmd=='latest': print(json.dumps(search('.evaluation-scores*',{'size':30,'sort':[{'@timestamp':'desc'}]}),indent=2));return 0
 if a.cmd=='ki': print(json.dumps(search('.significant_events-knowledge_indicators',{'size':200,'query':{'match_all':{}}}),indent=2));return 0
 if a.cmd=='scores':
  values=collections.defaultdict(list)
  for d in docs(a.exp): values[d.get('evaluator',{}).get('name','?')].append(d.get('evaluator',{}).get('score',0))
  print(json.dumps({k:sum(v)/len(v) for k,v in values.items()},indent=2));return 0
 if a.cmd=='failures': print(json.dumps([d for d in docs(a.exp,a.metric) if d.get('evaluator',{}).get('score',1)<1],indent=2));return 0
 if a.cmd=='trace': print(json.dumps([d for d in docs(a.exp,a.metric) if d.get('example',{}).get('id')==a.example],indent=2));return 0
 if a.cmd=='flips':
  def failed(e):return {(d.get('example',{}).get('id'),d.get('evaluator',{}).get('name')) for d in docs(e) if d.get('evaluator',{}).get('score',1)<1}
  print(json.dumps({'only_a':sorted(failed(a.expA)-failed(a.expB)),'only_b':sorted(failed(a.expB)-failed(a.expA))}));return 0
 grouped=collections.Counter()
 for exp in a.exp:
  for d in docs(exp):
   ev=d.get('evaluator',{}); text=' '.join(ev.get('explanation','').lower().split()[:8]);
   if ev.get('score',1)<1: grouped[(ev.get('name','?'),text)]+=1
 print(json.dumps({f'{k[0]}: {k[1]}':v for k,v in grouped.items()},indent=2));return 0
if __name__=='__main__':sys.exit(main())
