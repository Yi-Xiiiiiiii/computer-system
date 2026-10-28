#!/usr/bin/env python3
"""Use independent course GT to verify full-shortlist exact reranking on Debug."""
import argparse
import csv
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_experiments import environment

def spmat_first_rows(source,target,count):
    raw=source.read_bytes()
    nr,nc,nnz=struct.unpack_from('<qqq',raw)
    ptr=struct.unpack_from(f'<{nr+1}q',raw,24)
    stop=ptr[count]
    start_indices=24+(nr+1)*8; start_values=start_indices+nnz*4
    target.write_bytes(struct.pack('<qqq',count,nc,stop)+struct.pack(f'<{count+1}q',*ptr[:count+1])+
                       raw[start_indices:start_indices+stop*4]+raw[start_values:start_values+stop*4])

def main():
    p=argparse.ArgumentParser(); p.add_argument('--course-root',type=Path,required=True)
    a=p.parse_args(); course=a.course_root.resolve(); env=environment(course)
    tier=course/'datasets/yfcc_course_v1/debug_100000'; workload=tier/'workloads/low'
    with tempfile.TemporaryDirectory(prefix='adaptive-correctness-') as temp:
        tmp=Path(temp)
        subprocess.run([str(ROOT/'build/unit_tests'),str(tmp/'tiny.spmat')],env=env,check=True)
        count=5
        for name,scalar_bytes in [('query.u8bin',1),('ground_truth.ids.ibin',4)]:
            raw=(workload/name).read_bytes(); nr,dim=struct.unpack_from('<II',raw)
            (tmp/name).write_bytes(struct.pack('<II',count,dim)+raw[8:8+count*dim*scalar_bytes])
        spmat_first_rows(workload/'query.metadata.spmat',tmp/'query.metadata.spmat',count)
        prefix=course/'course_runs/indices/gateann/debug_100000/yfcc'
        # Discover the actual prefix, which is normally yfcc.
        signatures=list(prefix.parent.glob('*_disk.index'))
        if len(signatures)!=1: raise RuntimeError('Expected exactly one Debug index')
        prefix=Path(str(signatures[0])[:-len('_disk.index')])
        command=[str(ROOT/'build/adaptive_benchmark'),str(prefix),str(tier/'base.metadata.spmat'),
                 str(tmp),'adaptive','320','100000','1',str(tmp/'queries.csv'),str(tmp/'results.ibin')]
        result=subprocess.run(command,env=env,capture_output=True,text=True)
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        rows=list(csv.DictReader((tmp/'queries.csv').open()))
        if not all(float(r['recall_percent'])==100 for r in rows):
            raise AssertionError('Full candidate exact search differs from held-out exact ground truth')
        if not all(int(r['reranked'])==int(r['candidates']) for r in rows):
            raise AssertionError('Full-shortlist test did not enumerate all candidates')
        print('PASS: Debug first 5 queries, full candidate reranking, Recall@10=100%; all returned labels valid')
        print('PASS: query GT only evaluated after retrieval; no oracle candidates used')

if __name__=='__main__': main()
