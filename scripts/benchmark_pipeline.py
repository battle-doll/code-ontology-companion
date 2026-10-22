#!/usr/bin/env python3
"""Opt-in synthetic local benchmark. No source execution, network or installation.

The 50-line files are small declarations padded with comments. Passing this
corpus is structural evidence, not proof of equivalent real-project capacity.
Each phase runs in a separate Python process so peak RSS is phase-specific.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / 'skills/manage-code-ontology/scripts'
sys.path.insert(0, str(SCRIPT_ROOT))
import pipeline_store as store


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def persist(path, value):
    store._atomic(path, value)


def peak_rss():
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == 'darwin' else value * 1024)
    except (ImportError, AttributeError):
        return None


def sample_file(index, variant=0):
    language = index % 5
    name = 'Item' + str(index)
    amount = str(variant + 1)
    if language == 0:
        suffix, lines, comment = '.py', ['class ' + name + ':', '    def compute(self, value):', '        return value + ' + amount], '#'
    elif language == 1:
        suffix, lines, comment = '.java', ['package synthetic;', 'public class ' + name + ' {', '  public int compute(int value) { return value + ' + amount + '; }', '}'], '//'
    elif language == 2:
        suffix, lines, comment = '.ts', ['export function ' + name + '(value: number): number {', '  return value + ' + amount + ';', '}'], '//'
    elif language == 3:
        suffix, lines, comment = '.go', ['package synthetic', 'func ' + name + '(value int) int {', '  return value + ' + amount, '}'], '//'
    else:
        suffix, lines, comment = '.sh', ['#!/bin/bash', name + '() {', '  printf safe', '}'], '#'
    lines += [comment + ' Synthetic non-executable fixture padding ' + str(i) + ' revision ' + str(variant) for i in range(50 - len(lines))]
    return f'module-{index % 100:03d}/item-{index:06d}' + suffix, '\n'.join(lines) + '\n'


def write_sample(repo, index, variant=0):
    relative, source = sample_file(index, variant)
    path = repo / relative
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(source, encoding='utf-8')


def record_digest(workspace):
    digest = hashlib.sha256()
    count = 0
    with store.open_reader(workspace) as reader:
        for record in reader.iter_records(page_size=200):
            digest.update(canonical(record)); digest.update(b'\n'); count += 1
    return {'sha256': digest.hexdigest(), 'recordCount': count}


def latency(values):
    ordered = sorted(values)
    return {'samples': len(values), 'p50Seconds': statistics.median(values),
            'p95Seconds': ordered[min(len(ordered)-1, int(len(ordered)*.95))], 'maxSeconds': max(values)}


def worker(folder, phase, count):
    repo, workspace = folder / 'source', folder / 'workspace'
    started = time.perf_counter()
    extra = {}
    if phase == 'full':
        result = store.initialize(repo, workspace, label='Synthetic scale fixture', max_files=count,
            max_total_bytes=4 * 1024**3, max_records=5000000, max_output_bytes=8 * 1024**3,
            max_run_seconds=7200)
    elif phase in ('no_change', 'incremental', 'delete_rename'):
        result = store.sync(workspace)
    elif phase == 'forced_full':
        result = store.sync(workspace, force=True)
    elif phase == 'query':
        cold, warm, sizes = [], [], []
        for _ in range(10):
            began = time.perf_counter(); answer = store.query(workspace, limit=50)
            cold.append(time.perf_counter()-began); sizes.append(len(canonical(answer)))
        with store.open_reader(workspace) as reader:
            for _ in range(20):
                began = time.perf_counter(); answer = reader.query(limit=50)
                warm.append(time.perf_counter()-began)
        result = {'status': 'measured', 'coldOpenTop50': latency(cold), 'pinnedSessionTop50': latency(warm),
                  'responseBytes': {'minimum': min(sizes), 'maximum': max(sizes)}}
    elif phase == 'cancel_recover':
        requested = [None]
        cancelled = [False]
        files_seen = [0]
        original = store._checkpoint
        def checkpoint(stage):
            if stage == 'after_file':
                files_seen[0] += 1
                if files_seen[0] == 10:
                    requested[0] = time.perf_counter(); cancelled[0] = True
        store._checkpoint = checkpoint
        try:
            store.sync(workspace, force=True, cancel=lambda: cancelled[0])
            raise RuntimeError('expected_cancellation_missing')
        except store.PipelineCancelled:
            stopped = time.perf_counter()
        finally:
            store._checkpoint = original
        def inventory():
            return {str(p.relative_to(workspace)): (p.stat().st_size,p.stat().st_mtime_ns)
                    for p in workspace.rglob('*') if p.is_file()}
        before = inventory(); time.sleep(.2); after = inventory()
        recovered = store.recover(workspace)
        result = {'status': 'recovered', 'cancelRequestToQuiescenceSeconds': stopped-requested[0],
                  'noWritesAfterStopObservedSeconds': .2, 'noWritesAfterStop': before == after,
                  'recoveredRunCount': recovered['recoveredRunCount']}
    else:
        raise ValueError('unknown_phase')
    elapsed = time.perf_counter()-started
    if phase in ('incremental', 'delete_rename', 'forced_full'):
        extra['semanticRecords'] = record_digest(workspace)
    safe_result = {key: result[key] for key in ('status','recordCount','coverage','buildStats','sourceFingerprint','analysisSpecId',
        'coldOpenTop50','pinnedSessionTop50','responseBytes','cancelRequestToQuiescenceSeconds',
        'noWritesAfterStopObservedSeconds','noWritesAfterStop','recoveredRunCount') if key in result}
    receipt = {'phase': phase, 'wallSeconds': elapsed, 'peakRssBytes': peak_rss(), 'result': safe_result, **extra}
    persist(folder / (phase + '.json'), receipt)
    print(json.dumps({'phase': phase, 'count': count, 'wallSeconds': elapsed, 'peakRssBytes': receipt['peakRssBytes']}, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--counts', type=int, nargs='+', default=[1000,10000,100000])
    parser.add_argument('--worker', choices=['full','no_change','incremental','delete_rename','forced_full','query','cancel_recover'])
    args = parser.parse_args()
    if args.worker:
        worker(args.output, args.worker, args.counts[0]); return
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    for count in args.counts:
        if not 1 <= count <= 100000:
            raise ValueError('count_out_of_range')
        folder = args.output / ('files-' + str(count))
        folder.mkdir(mode=0o700)
        repo = folder / 'source'; repo.mkdir(mode=0o700)
        started = time.perf_counter()
        for index in range(count):
            write_sample(repo,index)
        summary = {'schemaVersion':1,'corpus':'synthetic-five-language-50-lines-comment-padded', 'files':count,
            'physicalLines':count*50,'languages':['Python','Java','TypeScript','Go','Shell'],'workers':1,
            'generationSeconds':time.perf_counter()-started,'platform':sys.platform,
            'capacityClaim':'synthetic_only_real_repositories_unverified','phases':[]}
        print(json.dumps({'phase':'generated','count':count,'wallSeconds':summary['generationSeconds']}),flush=True)
        phases = ['full','no_change','incremental','delete_rename','forced_full','query']
        if count == min(args.counts):
            phases.append('cancel_recover')
        for phase in phases:
            if phase == 'incremental':
                for offset in range(count//20):
                    write_sample(repo,(offset*19)%count,1)
            if phase == 'delete_rename':
                width=max(1,count//200)
                for index in range(width):
                    relative,_=sample_file(index); (repo/relative).unlink()
                for index in range(width,2*width):
                    relative,_=sample_file(index); path=repo/relative
                    path.rename(path.with_name('renamed-'+path.name))
            print(json.dumps({'phase':phase,'count':count,'state':'started'}),flush=True)
            completed = subprocess.run([sys.executable,__file__,'--output',str(folder),'--counts',str(count),'--worker',phase],check=False)
            if completed.returncode:
                summary['failure']={'phase':phase,'exitCode':completed.returncode}
                persist(folder/'summary.json',summary)
                raise RuntimeError('benchmark_worker_failed')
            summary['phases'].append(json.loads((folder/(phase+'.json')).read_text()))
            persist(folder/'summary.json',summary)
        records = {phase['phase']:phase.get('semanticRecords') for phase in summary['phases']}
        summary['fullIncrementalSemanticEquality'] = records['delete_rename'] == records['forced_full']
        persist(folder/'summary.json',summary)
        print(json.dumps({'phase':'completed','count':count,'fullIncrementalSemanticEquality':summary['fullIncrementalSemanticEquality']}),flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status':'failed','errorType':type(error).__name__}),file=sys.stderr)
        raise SystemExit(1)
