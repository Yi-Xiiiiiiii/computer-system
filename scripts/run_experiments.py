#!/usr/bin/env python3
"""Fresh paired baseline/optimization runs; preserves every command and log."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]

def environment(course):
    env = os.environ.copy()
    local = course/'course_runs/deps/root/usr/lib/x86_64-linux-gnu/openblas-pthread'
    if local.is_dir():
        env['LD_LIBRARY_PATH'] = str(local) + ':' + env.get('LD_LIBRARY_PATH', '')
    env['OPENBLAS_NUM_THREADS'] = '1'
    env['OMP_NUM_THREADS'] = '1'
    return env

def run_case(binary, prefix, meta, workload, policy, L, m, threshold, out, env):
    out.mkdir(parents=True, exist_ok=False)
    command = [str(binary), str(prefix), str(meta), str(workload), policy,
               str(L), str(m), str(threshold), str(out/'queries.csv'), str(out/'results.ids.ibin')]
    start = time.monotonic()
    with (out/'run.log').open('w') as log:
        result = subprocess.run(['/usr/bin/time','-v','-o',str(out/'resources.txt'),*command],
                                env=env, stdout=log, stderr=subprocess.STDOUT)
    record = {'command': command, 'exit_code': result.returncode,
              'elapsed_seconds': time.monotonic()-start,
              'environment': {k:env[k] for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS')}}
    (out/'command.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Failed: {out}/run.log')
    rows = list(csv.DictReader((out/'queries.csv').open()))
    rss = next(int(line.split(':')[-1]) for line in (out/'resources.txt').read_text().splitlines()
               if 'Maximum resident set size' in line)
    phase_us = float(rows[0]['query_phase_us'])
    average = lambda key: sum(float(r[key]) for r in rows)/len(rows)
    return dict(queries=len(rows), recall_percent=average('recall_percent'),
                mean_latency_us=average('query_us'),phase_latency_us=phase_us/len(rows),
                qps=len(rows)*1e6/phase_us,mean_ios=average('logical_ios'),
                filter_skips=average('filter_skips'),tunnel_us=average('tunnel_us'),
                route_us=average('route_us'),pq_us=average('pq_us'),rerank_us=average('rerank_us'),
                candidates=average('candidates'),reranked=average('reranked'),
                enumerated=sum(int(r['enumerated']) for r in rows),peak_rss_kb=rss,
                postings_build_ms=float(rows[0]['postings_build_us'])/1000,
                postings_bytes=int(rows[0]['postings_bytes']),elapsed_seconds=record['elapsed_seconds'])

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--course-root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--pilot',action='store_true')
    a=p.parse_args()
    if a.repeats<1: p.error('--repeats must be positive')
    course=a.course_root.resolve(); out=a.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    tier=course/'datasets/yfcc_course_v1/formal_1000000'
    prefix=course/'course_runs/indices/gateann/formal_1000000/yfcc'
    env=environment(course)
    configs=[('low','graph',320,40,0.01),('low','graph',1280,40,0.01)]
    configs += [('low','adaptive',320,m,0.01) for m in (10,20,40,80,160)]
    if not a.pilot:
        configs += [(bucket,policy,320,40,0.01) for bucket in ('medium','high') for policy in ('graph','adaptive')]
        configs += [('low','adaptive',320,40,t) for t in (0.0,0.005)]
    metadata={'platform':platform.platform(),'cpu_count':os.cpu_count(),
              'load_average':os.getloadavg(),'started_local':time.strftime('%Y-%m-%d %H:%M:%S %z'),
              'configs':configs,'repeats':a.repeats,
              'gateann_commit':subprocess.check_output(['git','-C',str(course/'systems/GateANN-public'),'rev-parse','HEAD'],text=True).strip(),
              'input_sha256':{}}
    for path in [tier/'base.metadata.spmat', Path(str(prefix)+'_disk.index'),
                 Path(str(prefix)+'_pq_compressed.bin'),Path(str(prefix)+'_pq_pivots.bin')]:
        h=hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(4*1024*1024),b''): h.update(block)
        metadata['input_sha256'][str(path.relative_to(course))]=h.hexdigest()
    metadata['extension_sha256']={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in sorted((ROOT/'src').glob('*'))}
    (out/'environment.json').write_text(json.dumps(metadata,indent=2))
    records=[]
    for repeat in range(1,a.repeats+1):
        # Reverse order on alternate repetitions to limit a consistent order bias.
        ordered=configs if repeat%2 else list(reversed(configs))
        for bucket,policy,L,m,t in ordered:
            name=f'{bucket}-{policy}-L{L}-M{m}-T{t:g}-r{repeat}'
            row=dict(repeat=repeat,bucket=bucket,policy=policy,L=L,M=m,threshold=t)
            row.update(run_case(ROOT/'build/adaptive_benchmark',prefix,tier/'base.metadata.spmat',
                                tier/'workloads'/bucket,policy,L,m,t,out/name,env))
            records.append(row)
            with (out/'results.csv').open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
            print(name,f"Recall={row['recall_percent']:.2f}% latency={row['mean_latency_us']/1000:.3f}ms",flush=True)
    print(out/'results.csv')

if __name__=='__main__': main()
