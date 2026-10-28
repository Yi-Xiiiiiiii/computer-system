#!/usr/bin/env python3
"""Aggregate three repeats, verify fallback equality, plot trade-offs."""
import argparse
import csv
from collections import defaultdict
import json
from pathlib import Path
from statistics import median

FIELDS=['recall_percent','mean_latency_us','qps','mean_ios','filter_skips','tunnel_us',
        'route_us','pq_us','rerank_us','candidates','reranked','enumerated',
        'peak_rss_kb','postings_build_ms','postings_bytes']

def summarize(root):
    rows=list(csv.DictReader((root/'results.csv').open()))
    groups=defaultdict(list)
    for row in rows:
        groups[(row['bucket'],row['policy'],int(row['L']),int(row['M']),float(row['threshold']))].append(row)
    output=[]
    for key,group in sorted(groups.items()):
        if len(group)!=3: raise ValueError(f'Expected 3 repetitions: {key}')
        record=dict(zip(['bucket','policy','L','M','threshold'],key)); record['repeats']=len(group)
        for field in FIELDS:
            vals=[float(r[field]) for r in group]
            for suffix,value in zip(('median','min','max'),(median(vals),min(vals),max(vals))):
                record[field+'_'+suffix]=value
        output.append(record)
    with (root/'summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(output[0])); writer.writeheader(); writer.writerows(output)
    # Verify that routing leaves both weaker-filter workloads exactly unchanged.
    checks=[]
    for repeat in (1,2,3):
        for bucket in ('medium','high','low'):
            base=root/f'{bucket}-graph-L320-M40-T0.01-r{repeat}'/'results.ids.ibin'
            threshold='0' if bucket=='low' else '0.01'
            opt=root/f'{bucket}-adaptive-L320-M40-T{threshold}-r{repeat}'/'results.ids.ibin'
            if base.read_bytes()!=opt.read_bytes(): raise ValueError(f'Fallback mismatch: {opt}')
            checks.append(f'{bucket} r{repeat}: identical result IDs')
    (root/'fallback_checks.json').write_text(json.dumps(checks,indent=2))
    per_label=defaultdict(list)
    for repeat in (1,2,3):
        case=root/f'low-adaptive-L320-M40-T0.01-r{repeat}'/'queries.csv'
        bylabel=defaultdict(list)
        for row in csv.DictReader(case.open()): bylabel[int(row['label_id'])].append(row)
        for label,qs in bylabel.items():
            per_label[label].append({'repeat':repeat,'queries':len(qs),'label':label,
                **{field:sum(float(q[field]) for q in qs)/len(qs)
                   for field in ('recall_percent','query_us','candidates')}})
    with (root/'per_label.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['label','repeat','queries','recall_percent','query_us','candidates'])
        writer.writeheader(); writer.writerows(r for rs in per_label.values() for r in rs)
    return output

def plot(root,summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    low=[r for r in summary if r['bucket']=='low' and r['threshold']==.01]
    fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
    for policy,color in [('graph','#1269a0'),('adaptive','#d86932')]:
        rs=sorted([r for r in low if r['policy']==policy],key=lambda r:r['mean_latency_us_median'])
        xs=[r['mean_latency_us_median']/1000 for r in rs]; ys=[r['recall_percent_median'] for r in rs]
        axes[0].plot(xs,ys,'-o',color=color,label='GateANN' if policy=='graph' else 'Adaptive')
        for r,x,y in zip(rs,xs,ys):
            axes[0].errorbar(x,y,xerr=[[x-r['mean_latency_us_min']/1000],[r['mean_latency_us_max']/1000-x]],color=color,capsize=3)
            axes[0].annotate(('L=' if policy=='graph' else 'M=')+str(r['L'] if policy=='graph' else r['M']),
                             (x,y),xytext=(5,-12 if y>95 else 5),textcoords='offset points',fontsize=8)
    axes[0].set(xlabel='Mean query latency (ms)',ylabel='Recall@10 (%)',title='Low: quality / latency')
    axes[0].legend(); axes[0].grid(alpha=.25)
    adaptive=sorted([r for r in low if r['policy']=='adaptive'],key=lambda r:r['M'])
    axes[1].plot([r['M'] for r in adaptive],[r['pq_us_median']/1000 for r in adaptive],'-o',label='PQ shortlist')
    axes[1].plot([r['M'] for r in adaptive],[r['rerank_us_median']/1000 for r in adaptive],'-s',label='AIO + exact rerank')
    axes[1].set(xlabel='Shortlist M',ylabel='Mean stage time (ms)',title='Adaptive stage costs')
    axes[1].grid(alpha=.25); axes[1].legend()
    fig.savefig(root/'optimization_comparison.png',dpi=200); plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--results',type=Path,required=True); a=p.parse_args()
    output=summarize(a.results); plot(a.results,output)
    print('PASS: 39 runs in 13 groups; 9 paired fallback ID comparisons; per-label statistics and plots written')
