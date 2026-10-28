#!/usr/bin/env python3
"""Build an additive driver with the pinned upstream target's exact ABI flags."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--gateann', type=Path, required=True)
parser.add_argument('--tests', action='store_true')
args = parser.parse_args()
gate = args.gateann.resolve()
commit = subprocess.check_output(['git', '-C', str(gate), 'rev-parse', 'HEAD'], text=True).strip()
if commit != '71e87cbf0e25c0400c0109dd25a64a7c4dccc9dd':
    raise SystemExit('Use the course-pinned GateANN commit')
entries = json.loads((gate/'build/compile_commands.json').read_text())
entry = next(x for x in entries if x['file'].endswith('/search_disk_index_yfcc.cpp'))
command = shlex.split(entry['command'])
if '-DUSE_AIO' not in command:
    raise SystemExit('GateANN must be configured with USE_AIO=ON')
build = ROOT/'build'
build.mkdir(exist_ok=True)
stem = 'unit_tests' if args.tests else 'benchmark'
command[command.index('-o')+1] = str(build/(stem+'.o'))
command[command.index('-c')+1] = str(ROOT/('tests/unit_tests.cpp' if args.tests else 'src/benchmark.cpp'))
command.insert(1, '-I'+str(ROOT/'src'))
command.insert(1, '-std=c++17')
subprocess.run(command, cwd=entry['directory'], check=True)
link_file = gate/'build/tests/CMakeFiles/search_disk_index_yfcc.dir/link.txt'
link = shlex.split(link_file.read_text())
link = [str(build/(stem+'.o')) if x.endswith('search_disk_index_yfcc.cpp.o') else x for x in link]
target = build/('unit_tests' if args.tests else 'adaptive_benchmark')
link[link.index('-o')+1] = str(target)
subprocess.run(link, cwd=gate/'build/tests', check=True)
print(target)
