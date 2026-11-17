"""Run every companion test script; exit non-zero if any reports a problem.

    uv run python tests/run_all.py
"""
import pathlib
import subprocess
import sys

here = pathlib.Path(__file__).resolve().parent
failed = []
for test in sorted(here.glob("test_*.py")):
    r = subprocess.run([sys.executable, str(test)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=here.parent)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    ok = r.returncode == 0 and last.startswith("OK")
    print(f"{'ok  ' if ok else 'FAIL'} {test.name}")
    if not ok:
        failed.append(test.name)
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
print(f"\n{len(failed)} failed: {', '.join(failed)}" if failed else "\nall passed")
sys.exit(1 if failed else 0)
