"""Static AST allow-list check for generated code (R-POL-1 to R-POL-4, R-POL-6).

R-POL-6 keeps the provenance trace honest (R-TRACE-3): photonsim may only be used through its
public API (so nothing can simulate without being recorded), the recorder's internals cannot be
named, imported modules and imported names cannot be patched (attribute assignment, ``del``,
``setattr``/``delattr``), and a module bound by ``import`` may only be used as ``module.attr``
(so it cannot be aliased or passed into a function to patch it there).

The policy runs before any execution. It is defence in depth: the sandbox (R-SBX-3) must hold
even when the policy is bypassed (R-POL-5). Violations are phrased so that they can be fed back
to the model as repair instructions.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

import photonsim

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

# Modules that allowed modules re-export as attributes (e.g. `matplotlib.os`,
# `matplotlib.subprocess`, `numpy.sys`). Reaching them through an attribute would bypass the
# import allow-list, so the attribute names themselves are rejected.
FORBIDDEN_MODULE_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "pathlib",
        "importlib",
        "builtins",
        "pickle",
        "tempfile",
        "io",
    }
)

# Process-replacing and process-creating functions: os.exec*, os.spawn*, os.posix_spawn*, fork.
_PROCESS_ATTRIBUTE = re.compile(
    r"^(exec[lv]p?e?|spawn[lv]p?e?|posix_spawnp?|fork|forkpty|vfork|startfile)$"
)

ALLOWED_DUNDER_NAMES: frozenset[str] = frozenset({"__name__"})

# R-POL-6: the only photonsim names generated code may use, and the recorder's internals.
PHOTONSIM_API: frozenset[str] = frozenset(photonsim.__all__)
RECORDER_NAMES: frozenset[str] = frozenset(
    {"_provenance", "RECORDER", "_Recorder", "run_simulation"}
)

_DUNDER = re.compile(r"^__\w+__$")
_FORMAT_DUNDER = re.compile(r"\{[^{}]*\.__\w+__")


def forbidden_attribute(name: str) -> str | None:
    """Why the attribute ``name`` is forbidden, or None if it is allowed."""
    if name in FORBIDDEN_MODULE_ATTRIBUTES:
        return (
            f"`.{name}` is not allowed: modules such as {name} may not be reached through "
            "another module's attributes"
        )
    if _PROCESS_ATTRIBUTE.match(name):
        return f"`.{name}` is not allowed (process creation)"
    if name in FORBIDDEN_ATTRIBUTES:
        return f"`.{name}` is not allowed (file, process or native access)"
    return None


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


def _root_name(node: ast.AST) -> str | None:
    """``a`` for ``a``, ``a.b``, ``a.b.c``; None for anything else (calls, subscripts, ...)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _target_nodes(target: ast.AST) -> Iterator[ast.AST]:
    """Every node bound by an assignment target, unpacking tuples, lists and starred names."""
    if isinstance(target, ast.Tuple | ast.List):
        for elt in target.elts:
            yield from _target_nodes(elt)
    elif isinstance(target, ast.Starred):
        yield from _target_nodes(target.value)
    else:
        yield target


@dataclass
class _Names:
    """Names bound by imports, found before checking (R-POL-6)."""

    modules: set[str] = field(default_factory=set)  # bound by `import x [as y]`
    photonsim: set[str] = field(default_factory=set)  # names bound to the photonsim package
    imported: set[str] = field(default_factory=set)  # modules, from-imports, module attributes

    @classmethod
    def collect(cls, tree: ast.AST) -> _Names:
        names = cls()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    names.modules.add(bound)
                    if alias.name.split(".")[0] == "photonsim" and (
                        alias.asname is None or alias.name == "photonsim"
                    ):
                        names.photonsim.add(bound)
            elif isinstance(node, ast.ImportFrom):
                names.imported.update(a.asname or a.name for a in node.names)
        names.imported |= names.modules
        # Names assigned from an imported name or its attribute chain (``r = np.random``, ``b = r``)
        # refer to the same objects: treat them as imported too, until nothing changes.
        changed = True
        while changed:
            changed = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
                    value = node.value
                    root = (
                        _root_name(value) if isinstance(value, ast.Attribute | ast.Name) else None
                    )
                    if root not in names.imported:
                        continue
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        for item in _target_nodes(target):
                            if isinstance(item, ast.Name) and item.id not in names.imported:
                                names.imported.add(item.id)
                                changed = True
        return names


class _Checker(ast.NodeVisitor):
    def __init__(self, names: _Names | None = None) -> None:
        self.violations: list[Violation] = []
        self.names = names or _Names()
        self._attribute_bases: set[int] = set()  # id() of Name nodes used as `name.attr`

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
            elif forbidden_attribute(alias.name) or _DUNDER.match(alias.name):
                self._add(node, f"importing `{alias.name}` from `{module}` is not allowed")
            elif alias.name in RECORDER_NAMES:
                self._add(node, _recorder_message(alias.name))
            elif module == "photonsim" and alias.name not in PHOTONSIM_API:
                self._add(node, _api_message(alias.name))
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
        obj, attr = node.args[0], node.args[1]
        root = _root_name(obj)
        if name in {"setattr", "delattr"} and root in self.names.imported:
            self._add(node, _patch_message(root))
            return
        if not (isinstance(attr, ast.Constant) and isinstance(attr.value, str)):
            self._add(
                node, f"`{name}()` needs a literal attribute name; use normal attribute access"
            )
        elif _DUNDER.match(attr.value) or forbidden_attribute(attr.value):
            self._add(node, f"`{name}()` on `{attr.value}` is not allowed")
        elif attr.value in RECORDER_NAMES:
            self._add(node, _recorder_message(attr.value))
        elif (
            isinstance(obj, ast.Name)
            and obj.id in self.names.photonsim
            and attr.value not in PHOTONSIM_API
        ):
            self._add(node, _api_message(attr.value))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name):
            self._attribute_bases.add(id(node.value))
        if _DUNDER.match(node.attr) and node.attr not in ALLOWED_DUNDER_NAMES:
            self._add(node, f"access to dunder attribute `{node.attr}` is not allowed")
        elif reason := forbidden_attribute(node.attr):
            self._add(node, reason)
        elif node.attr in RECORDER_NAMES:
            self._add(node, _recorder_message(node.attr))
        elif (
            isinstance(node.value, ast.Name)
            and node.value.id in self.names.photonsim
            and node.attr not in PHOTONSIM_API
        ):
            self._add(node, _api_message(node.attr))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if _DUNDER.match(node.id) and node.id not in ALLOWED_DUNDER_NAMES:
            self._add(node, f"use of `{node.id}` is not allowed")
        elif node.id in FORBIDDEN_CALLS | ATTRIBUTE_BUILTINS:
            # e.g. `f = eval` or passing `open` around; direct calls are handled in visit_Call.
            self._add(node, f"use of `{node.id}` is not allowed")
        elif node.id in RECORDER_NAMES:
            self._add(node, _recorder_message(node.id))
        elif (
            isinstance(node.ctx, ast.Load)
            and node.id in self.names.modules
            and id(node) not in self._attribute_bases
        ):
            self._add(
                node,
                f"module `{node.id}` may only be used as `{node.id}.<name>`; "
                "do not store it, pass it to a function or alias it",
            )

    # R-POL-6: no patching of imported modules or imported names.
    def _check_targets(self, targets: list[ast.expr]) -> None:
        for target in targets:
            for bound in _target_nodes(target):
                # Item assignment (``plt.rcParams["font.size"] = 12``) is fine: it cannot
                # replace a module's functions, and dunder access is rejected elsewhere.
                if isinstance(bound, ast.Attribute):
                    root = _root_name(bound.value)
                    if root in self.names.imported:
                        self._add(bound, _patch_message(root))

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_targets(node.targets)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_targets([node.target])
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_targets([node.target])
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        self._check_targets(node.targets)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._check_targets([node.target])
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._check_targets([node.target])
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self._check_targets([i.optional_vars for i in node.items if i.optional_vars is not None])
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _FORMAT_DUNDER.search(node.value):
            self._add(node, "format strings that access dunder attributes are not allowed")


def _api_message(name: str) -> str:
    api = ", ".join(sorted(PHOTONSIM_API))
    return f"`{name}` is not part of the photonsim API; use only: {api}"


def _recorder_message(name: str) -> str:
    return f"`{name}` is internal to photonsim's provenance recorder and may not be used"


def _patch_message(root: str) -> str:
    return (
        f"modifying `{root}` is not allowed: imported modules and imported names may not be "
        "patched (no attribute assignment, del, setattr or delattr)"
    )


def check(code: str) -> PolicyResult:
    """Parse ``code`` and check it against the allow-list. Nothing is executed."""
    try:
        tree = ast.parse(code, filename="script.py", mode="exec")
    except SyntaxError as exc:
        msg = exc.msg or "invalid syntax"
        return PolicyResult([Violation(exc.lineno, f"SyntaxError: {msg}")])
    except ValueError as exc:  # e.g. null bytes in the source
        return PolicyResult([Violation(None, f"the script could not be parsed: {exc}")])
    checker = _Checker(_Names.collect(tree))
    checker.visit(tree)
    unique = list(dict.fromkeys(checker.violations))
    return PolicyResult(sorted(unique, key=lambda v: (v.line or 0, v.message)))
