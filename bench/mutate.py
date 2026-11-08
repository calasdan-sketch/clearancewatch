"""Mutation sanity check: break the checks one condition at a time and see whether the tests notice.

    python bench/mutate.py                 # every comparison / and-or / not in audit.py and money.py
    python bench/mutate.py audit 30        # only audit.py, only the first 30 mutants

Each mutant changes ONE thing (``<`` to ``<=``, ``and`` to ``or``, ``not x`` to ``x``, ``==`` to ``!=``,
...) in a throw-away copy of the package under the system temp folder, then runs the test suite against that
copy. A mutant the tests fail on is "killed" (good). One that still passes is a "survivor": either an
equivalent change (nothing observable differs) or a gap in the tests. The repo itself is never edited.
"""
from __future__ import annotations

import ast
import copy
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
        ast.Is: ast.IsNot, ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In}


class Mutator(ast.NodeTransformer):
    def __init__(self, target: int, lines=()):
        self.target, self.seen, self.what, self.lines = target, -1, "", lines

    def _hit(self, label: str, node: ast.AST) -> bool:
        self.seen += 1
        if self.seen == self.target:
            n = getattr(node, "lineno", 0)
            code = self.lines[n - 1].strip()[:90] if 0 < n <= len(self.lines) else ""
            self.what = f"line {n}: {label}   | {code}"
            return True
        return False

    def visit_Compare(self, node: ast.Compare):
        self.generic_visit(node)
        for i, op in enumerate(node.ops):
            if type(op) in SWAP and self._hit(f"{type(op).__name__} -> {SWAP[type(op)].__name__}", node):
                node.ops[i] = SWAP[type(op)]()
        return node

    def visit_BoolOp(self, node: ast.BoolOp):
        self.generic_visit(node)
        if self._hit("and <-> or", node):
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and self._hit("not x -> x", node):
            return node.operand
        return node


def count(tree: ast.AST) -> int:
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            n += sum(1 for op in node.ops if type(op) in SWAP)
        elif isinstance(node, ast.BoolOp):
            n += 1
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            n += 1
    return n


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 9
    names = [n for n in ("audit", "money") if not only or n == only]
    killed = survived = 0
    survivors = []
    with tempfile.TemporaryDirectory(prefix="cw-mutate-") as tmp:
        for name in names:
            src_path = os.path.join(ROOT, "src", "clearancewatch", name + ".py")
            source = open(src_path, encoding="utf-8").read()
            total = count(ast.parse(source))
            for k in range(min(total, limit)):
                work = os.path.join(tmp, f"{name}-{k}")
                shutil.copytree(os.path.join(ROOT, "src"), os.path.join(work, "src"),
                                ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
                m = Mutator(k, source.splitlines())
                tree = m.visit(copy.deepcopy(ast.parse(source)))
                ast.fix_missing_locations(tree)
                with open(os.path.join(work, "src", "clearancewatch", name + ".py"), "w", encoding="utf-8") as fh:
                    fh.write(ast.unparse(tree))
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
                try:
                    r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider",
                                        "-o", f"pythonpath={os.path.join(work, 'src')}",
                                        "--rootdir", ROOT, os.path.join(ROOT, "tests")],
                                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
                    dead = r.returncode != 0
                except subprocess.TimeoutExpired:
                    dead = True  # an infinite loop is noticed too
                shutil.rmtree(work, ignore_errors=True)
                if dead:
                    killed += 1
                else:
                    survived += 1
                    survivors.append(f"{name}.py {m.what}")
    total = killed + survived
    print(f"mutants: {total}  killed: {killed}  survived: {survived}  score: {100 * killed // max(total, 1)}%")
    for s in survivors:
        print("  survived:", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
