"""Sandboxed expression language for guards and action arguments.

Syntax is a strict subset of Python expressions, parsed with :mod:`ast` and
interpreted by a whitelist walker (never ``eval``):

* literals (numbers, strings, booleans, ``None``), lists, tuples, dicts;
* names resolved from the evaluation context (local variables, parameters,
  the triggering message, constants);
* attribute access on context records (``msg.value``, ``msg.time``) -- only on
  :class:`Record` objects, so no Python object internals are reachable;
* subscripts, arithmetic (``+ - * / // % **``), bitwise (``^ & | ~``),
  comparisons (including chained), ``and``/``or``/``not``, ``x if c else y``;
* calls to whitelisted functions only (see :data:`FUNCTIONS`).

Randomness functions draw from the participant's own seeded RNG stream, so
expressions are reproducible.  Time values in expressions are float
nanoseconds of the participant's *local* clock.
"""

from __future__ import annotations

import ast
import math
from functools import lru_cache
from typing import Any, Callable, Dict, Mapping

_MAX_POW = 10_000


class ExprError(ValueError):
    def __init__(self, message: str, expr: str = ""):
        super().__init__(f"{message} in expression {expr!r}" if expr else message)
        self.expr = expr


class Record(dict):
    """A read-only mapping exposed with attribute syntax inside expressions."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item) from None


def _xor(*bits):
    r = 0
    for b in bits:
        r ^= int(b)
    return r


def _distance(p, q):
    return math.dist(tuple(float(x) for x in p), tuple(float(x) for x in q))


# functions that do not need context
PURE_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "abs": abs, "min": min, "max": max, "int": int, "float": float, "bool": bool,
    "round": round, "len": len, "sum": sum, "str": str,
    "sqrt": math.sqrt, "cos": math.cos, "sin": math.sin, "exp": math.exp, "log": math.log,
    "floor": math.floor, "ceil": math.ceil,
    "xor": _xor, "distance": _distance,
}

# functions bound by the engine to the participant's context (see engine._functions)
ENGINE_FUNCTIONS = {
    "rand_bit": "uniform random bit from the participant's own RNG stream",
    "rand_int": "rand_int(lo, hi): uniform integer in [lo, hi]",
    "rand_uniform": "uniform float in [0, 1)",
    "rand_choice": "rand_choice(list): uniform element",
    "travel_ns": "travel_ns(distance_m): light-cone delay at the project signal speed",
    "fs_round": "fs_round(x_ns): snap a time in ns to the engine's femtosecond grid",
}

CONSTANTS = {"pi": math.pi, "true": True, "false": False, "null": None,
             "True": True, "False": False, "None": None}

_BINOPS = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
    ast.BitXor: lambda a, b: a ^ b, ast.BitAnd: lambda a, b: a & b,
    ast.BitOr: lambda a, b: a | b,
}
_CMPOPS = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}


@lru_cache(maxsize=4096)
def parse(expr: str) -> ast.Expression:
    if not isinstance(expr, str):
        raise ExprError(f"expression must be a string, got {type(expr).__name__}")
    if len(expr) > 2000:
        raise ExprError("expression too long", expr[:40])
    try:
        tree = ast.parse(expr.strip() or "None", mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"syntax error: {exc.msg}", expr) from None
    _check(tree, expr)
    return tree


_ALLOWED = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Attribute, ast.Subscript,
    ast.Index if hasattr(ast, "Index") else ast.Constant, ast.Slice,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call,
    ast.List, ast.Tuple, ast.Dict, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Invert, ast.Pow, *_BINOPS.keys(), *_CMPOPS.keys(),
)


def _check(tree: ast.AST, expr: str) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ExprError(f"construct {type(node).__name__} is not allowed", expr)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExprError("private attribute access is not allowed", expr)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ExprError("only direct calls of whitelisted functions are allowed", expr)
            if node.keywords:
                raise ExprError("keyword arguments are not supported", expr)


def names_used(expr: str) -> set:
    tree = parse(expr)
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - called


def functions_used(expr: str) -> set:
    tree = parse(expr)
    return {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)}


def evaluate(expr: Any, context: Mapping[str, Any], functions: Mapping[str, Callable] | None = None) -> Any:
    """Evaluate ``expr``.  Non-string values (numbers, bools, lists) pass through."""
    if not isinstance(expr, str):
        return expr
    tree = parse(expr)
    funcs = dict(PURE_FUNCTIONS)
    if functions:
        funcs.update(functions)
    try:
        return _eval(tree.body, context, funcs, expr)
    except ExprError:
        raise
    except Exception as exc:  # arithmetic errors etc.
        raise ExprError(f"{type(exc).__name__}: {exc}", expr) from None


def _eval(node, ctx, funcs, expr):
    ev = lambda n: _eval(n, ctx, funcs, expr)  # noqa: E731
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in ctx:
            return ctx[node.id]
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise ExprError(f"unknown name {node.id!r}", expr)
    if isinstance(node, ast.Attribute):
        base = ev(node.value)
        if not isinstance(base, Record):
            raise ExprError(f"attribute access .{node.attr} on non-record value", expr)
        if node.attr not in base:
            raise ExprError(f"record has no field {node.attr!r} (fields: {sorted(base)})", expr)
        return base[node.attr]
    if isinstance(node, ast.Subscript):
        base = ev(node.value)
        if not isinstance(base, (list, tuple, dict, str)):
            raise ExprError("subscript on unsupported value", expr)
        sl = node.slice
        if isinstance(sl, ast.Slice):
            return base[slice(ev(sl.lower) if sl.lower else None,
                              ev(sl.upper) if sl.upper else None,
                              ev(sl.step) if sl.step else None)]
        return base[ev(sl)]
    if isinstance(node, ast.BinOp):
        a, b = ev(node.left), ev(node.right)
        if isinstance(node.op, ast.Pow):
            if isinstance(b, (int, float)) and abs(b) > _MAX_POW:
                raise ExprError("exponent too large", expr)
            return a ** b
        return _BINOPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp):
        v = ev(node.operand)
        if isinstance(node.op, ast.Not):
            return not v
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
        if isinstance(node.op, ast.Invert):
            return ~v
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            r = True
            for v in node.values:
                r = ev(v)
                if not r:
                    return r
            return r
        r = False
        for v in node.values:
            r = ev(v)
            if r:
                return r
        return r
    if isinstance(node, ast.Compare):
        left = ev(node.left)
        for op, comp in zip(node.ops, node.comparators):
            right = ev(comp)
            if not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return ev(node.body) if ev(node.test) else ev(node.orelse)
    if isinstance(node, ast.Call):
        name = node.func.id
        if name not in funcs:
            raise ExprError(f"function {name!r} is not available", expr)
        return funcs[name](*[ev(a) for a in node.args])
    if isinstance(node, ast.List):
        return [ev(e) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(ev(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return {ev(k): ev(v) for k, v in zip(node.keys, node.values)}
    raise ExprError(f"unsupported construct {type(node).__name__}", expr)


def validate_syntax(expr: Any) -> str | None:
    """Return an error message or None."""
    if not isinstance(expr, str):
        return None
    try:
        parse(expr)
    except ExprError as exc:
        return str(exc)
    return None
