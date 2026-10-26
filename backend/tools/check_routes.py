"""路由自检：route_after_* 的所有返回值必须出现在对应的条件边映射里。

这类漏映射会让整轮直接 failed（比如 'quick_reply'），而且只在特定分支才触发，
靠人工点测很难覆盖。这里用 AST 静态检查。
"""
from __future__ import annotations

import ast
import pathlib
import sys

GRAPH = pathlib.Path(r"D:\workspaces\minimax\director-console\backend\app\agent\graph.py")


def route_returns(tree: ast.Module) -> dict[str, set[str]]:
    """收集每个 route_after_* 函数 return 的字符串常量。"""
    found: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("route_after"):
            values: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return):
                    expr = sub.value
                    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                        values.add(expr.value)
                    elif isinstance(expr, ast.IfExp):
                        for branch in (expr.body, expr.orelse):
                            if isinstance(branch, ast.Constant) and isinstance(branch.value, str):
                                values.add(branch.value)
            found[node.name] = values
    return found


def edge_mappings(tree: ast.Module) -> dict[str, set[str]]:
    """收集 add_conditional_edges 里每个 route 函数的映射键。"""
    result: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_conditional_edges"):
            continue
        if len(node.args) < 3:
            continue
        route = node.args[1]
        name = getattr(route, "id", None)
        mapping = node.args[2]
        if not name or not isinstance(mapping, ast.Dict):
            continue
        keys = {k.value for k in mapping.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        result.setdefault(name, set()).update(keys)
    return result


def main() -> int:
    tree = ast.parse(GRAPH.read_text(encoding="utf-8"))
    routes = route_returns(tree)
    mappings = edge_mappings(tree)
    problems = 0
    for name, values in routes.items():
        if name not in mappings:
            continue
        missing = values - mappings[name]
        if missing:
            problems += 1
            print(f"[FAIL] {name} 返回了 {sorted(missing)}，但映射里没有")
        else:
            print(f"[PASS] {name} → {sorted(values)}")
    print("\n路由自检：" + ("全部通过" if not problems else f"{problems} 处漏映射"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
