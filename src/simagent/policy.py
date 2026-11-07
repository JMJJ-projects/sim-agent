"""Static AST allow-list check for generated code (R-POL-1 to R-POL-4).

The policy runs before any execution. It is defence in depth: the sandbox (R-SBX-3) must hold
even when the policy is bypassed (R-POL-5). Violations are phrased so that they can be fed back
to the model as repair instructions.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        "photonsim",
        "simagent_io",
        "numpy",
        "math",
        "json",
        "statistics",
        "itertools",
        "matplotlib",
        "matplotlib.pyplot",
    }
)

FORBIDDEN_CALLS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "globals",
        "locals",
        "vars",
        "input",
        "breakpoint",
        "help",
        "memoryview",
    }
)

ATTRIBUTE_BUILTINS: frozenset[str] = frozenset({"getattr", "setattr", "delattr", "hasattr"})

# Attributes of allowed modules that reach files, processes or native code.
FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "ctypeslib",
        "f2py",
        "ctypes",
        "load",
        "loadtxt",
        "genfromtxt",
        "fromfile",
        "fromregex",
        "tofile",
        "memmap",
        "save",
        "savez",
        "savez_compressed",
        "savetxt",
        "DataSource",
        "system",
        "popen",
    }
)

ALLOWED_DUNDER_NAMES: frozenset[str] = frozenset({"__name__"})

_DUNDER = re.compile(r"^__\w+__$")
_FORMAT_DUNDER = re.compile(r"\{[^{}]*\.__\w+__")


@dataclass(frozen=True)
class Violation:
    """One policy violation, with the source line when known."""

    line: int | None
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}" if self.line else self.message


@dataclass(frozen=True)
class PolicyResult:
    """Outcome of ``check``. ``ok`` is True when there are no violations."""

    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def feedback(self) -> str:
        """Repair feedback for the model (R-POL-4)."""
        if self.ok:
            return "no policy violations"
        lines = ["The script was rejected by the static policy and was not run:"]
        lines += [f"- {v}" for v in self.violations]
        return "\n".join(lines)


def _allowed_list() -> str:
    return ", ".join(sorted(ALLOWED_MODULES))


def _module_allowed(name: str) -> bool:
    return name in ALLOWED_MODULES


class _Checker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[Violation] = []

    def _add(self, node: ast.AST, message: str) -> None:
        self.violations.append(Violation(getattr(node, "lineno", None), message))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if not _module_allowed(alias.name):
                allowed = _allowed_list()
                self._add(
                    node, f"import of `{alias.name}` is not allowed; allowed modules are {allowed}"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level:
            self._add(node, "relative imports are not allowed")
        elif not _module_allowed(module):
            self._add(
                node,
                f"import from `{module}` is not allowed; allowed modules are {_allowed_list()}",
            )
        for alias in node.names:
            if alias.name == "*":
                self._add(node, f"`from {module} import *` is not allowed; import names explicitly")
            elif alias.name in FORBIDDEN_ATTRIBUTES or _DUNDER.match(alias.name):
                self._add(node, f"importing `{alias.name}` from `{module}` is not allowed")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in FORBIDDEN_CALLS:
                hint = (
                    "; report results with simagent_io.submit(answer, **data)"
                    if func.id == "open"
                    else ""
                )
                self._add(node, f"call to `{func.id}()` is not allowed{hint}")
            elif func.id in ATTRIBUTE_BUILTINS:
                self._check_attribute_builtin(node, func.id)
            elif _DUNDER.match(func.id) and func.id not in ALLOWED_DUNDER_NAMES:
                self._add(node, f"use of `{func.id}` is not allowed")
            # The callee name is fully handled here; visit only the arguments.
            for child in [*node.args, *node.keywords]:
                self.visit(child)
            return
        self.generic_visit(node)

    def _check_attribute_builtin(self, node: ast.Call, name: str) -> None:
        if len(node.args) < 2:
            return
        attr = node.args[1]
        if not (isinstance(attr, ast.Constant) and isinstance(attr.value, str)):
            self._add(
                node, f"`{name}()` needs a literal attribute name; use normal attribute access"
            )
        elif _DUNDER.match(attr.value) or attr.value in FORBIDDEN_ATTRIBUTES:
            self._add(node, f"`{name}()` on `{attr.value}` is not allowed")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if _DUNDER.match(node.attr) and node.attr not in ALLOWED_DUNDER_NAMES:
            self._add(node, f"access to dunder attribute `{node.attr}` is not allowed")
        elif node.attr in FORBIDDEN_ATTRIBUTES:
            self._add(node, f"`.{node.attr}` is not allowed (file, process or native access)")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if _DUNDER.match(node.id) and node.id not in ALLOWED_DUNDER_NAMES:
            self._add(node, f"use of `{node.id}` is not allowed")
        elif node.id in FORBIDDEN_CALLS | ATTRIBUTE_BUILTINS:
            # e.g. `f = eval` or passing `open` around; direct calls are handled in visit_Call.
            self._add(node, f"use of `{node.id}` is not allowed")

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _FORMAT_DUNDER.search(node.value):
            self._add(node, "format strings that access dunder attributes are not allowed")


def check(code: str) -> PolicyResult:
    """Parse ``code`` and check it against the allow-list. Nothing is executed."""
    try:
        tree = ast.parse(code, filename="script.py", mode="exec")
    except SyntaxError as exc:
        msg = exc.msg or "invalid syntax"
        return PolicyResult([Violation(exc.lineno, f"SyntaxError: {msg}")])
    except ValueError as exc:  # e.g. null bytes in the source
        return PolicyResult([Violation(None, f"the script could not be parsed: {exc}")])
    checker = _Checker()
    checker.visit(tree)
    unique = list(dict.fromkeys(checker.violations))
    return PolicyResult(sorted(unique, key=lambda v: (v.line or 0, v.message)))
