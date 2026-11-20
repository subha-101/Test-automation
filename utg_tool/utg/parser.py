"""Clang (libclang) C parser -> Function IR   (Modules 2 and 3).

No regular expressions are used to understand C.  Everything semantic (types, scopes, referenced
declarations, implicit conversions) comes from the Clang AST.  Two libclang weaknesses are handled
explicitly instead of guessing:

* nodes that originate from macro expansion carry no tokens  -> operators are read from the exact source
  bytes between operand extents; constant sub-expressions are folded with Clang's own constant evaluator.
* a *fatal* diagnostic (e.g. a missing #include) makes Clang stop reporting later errors  -> any unresolved
  type becomes an explicit "unsupported" entry and a blocking diagnostic; nothing is silently ignored.
"""
from __future__ import annotations

import ctypes
import os
from typing import Optional

import clang.cindex as ci
from clang.cindex import CursorKind as CK, TypeKind as TK, StorageClass

from .config import ProjectConfig
from .ir import (Atom, CallInfo, Condition, Expr, FunctionIR, SourceLoc, Stmt, TypeInfo, VarInfo)

# ------------------------------------------------------------------------------------------------------------
# libclang constant evaluator (not wrapped by the python bindings)
# ------------------------------------------------------------------------------------------------------------
_lib = ci.conf.lib
_lib.clang_Cursor_Evaluate.argtypes = [ci.Cursor]
_lib.clang_Cursor_Evaluate.restype = ctypes.c_void_p
_lib.clang_EvalResult_getKind.argtypes = [ctypes.c_void_p]
_lib.clang_EvalResult_getKind.restype = ctypes.c_int
_lib.clang_EvalResult_getAsLongLong.argtypes = [ctypes.c_void_p]
_lib.clang_EvalResult_getAsLongLong.restype = ctypes.c_longlong
_lib.clang_EvalResult_getAsUnsigned.argtypes = [ctypes.c_void_p]
_lib.clang_EvalResult_getAsUnsigned.restype = ctypes.c_ulonglong
_lib.clang_EvalResult_isUnsignedInt.argtypes = [ctypes.c_void_p]
_lib.clang_EvalResult_isUnsignedInt.restype = ctypes.c_uint
_lib.clang_EvalResult_getAsDouble.argtypes = [ctypes.c_void_p]
_lib.clang_EvalResult_getAsDouble.restype = ctypes.c_double
_lib.clang_EvalResult_dispose.argtypes = [ctypes.c_void_p]


def evaluate_const(c) -> Optional[object]:
    """Constant value of a cursor (int or float) or None."""
    r = _lib.clang_Cursor_Evaluate(c)
    if not r:
        return None
    try:
        k = _lib.clang_EvalResult_getKind(r)
        if k == 1:
            if _lib.clang_EvalResult_isUnsignedInt(r):
                return int(_lib.clang_EvalResult_getAsUnsigned(r))
            return int(_lib.clang_EvalResult_getAsLongLong(r))
        if k == 2:
            return float(_lib.clang_EvalResult_getAsDouble(r))
        return None
    finally:
        _lib.clang_EvalResult_dispose(r)


_SIGNED = {TK.CHAR_S, TK.SCHAR, TK.SHORT, TK.INT, TK.LONG, TK.LONGLONG, TK.INT128}
_UNSIGNED = {TK.CHAR_U, TK.UCHAR, TK.USHORT, TK.UINT, TK.ULONG, TK.ULONGLONG, TK.UINT128}
_REL = {"<", "<=", ">", ">=", "==", "!="}
_BIN = {"+", "-", "*", "/", "%", "<<", ">>", "&", "|", "^", "&&", "||", "<", "<=", ">", ">=", "==", "!=", ","}
_ASSIGN = {"=", "+=", "-=", "*=", "/=", "%=", "<<=", ">>=", "&=", "|=", "^="}
_UNARY = {"-", "+", "!", "~", "*", "&", "++", "--"}


class _SourceReader:
    """Reads exact source bytes (CRLF safe: Clang offsets are byte offsets)."""

    def __init__(self) -> None:
        self._cache: dict = {}

    def data(self, path: str) -> bytes:
        if path not in self._cache:
            try:
                with open(path, "rb") as fh:
                    self._cache[path] = fh.read()
            except OSError:
                self._cache[path] = b""
        return self._cache[path]

    def slice(self, path: str, start: int, end: int) -> str:
        return self.data(path)[start:end].decode("utf-8", "replace")

    def extent_text(self, c) -> str:
        f = c.extent.start.file
        if f is None or c.extent.end.file is None or f.name != c.extent.end.file.name:
            return ""
        return " ".join(self.slice(f.name, c.extent.start.offset, c.extent.end.offset).split())


def _strip_noise(s: str) -> str:
    """Remove comments, parentheses and whitespace from the text between two operands."""
    out, i = [], 0
    while i < len(s):
        if s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = len(s) if j < 0 else j + 2
        elif s.startswith("//", i):
            j = s.find("\n", i)
            i = len(s) if j < 0 else j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out).replace("(", "").replace(")", "").strip()


def _loc(c) -> SourceLoc:
    l = c.location
    return SourceLoc(l.file.name if l.file else "", l.line, l.column)


class ParseError(RuntimeError):
    pass


class CParser:
    def __init__(self, cfg: ProjectConfig) -> None:
        self.cfg = cfg
        self.reader = _SourceReader()
        self.tu = None
        self.diagnostics: list = []

    # -------------------------------------------------------------------------------------------------------
    # translation unit
    # -------------------------------------------------------------------------------------------------------
    def parse(self) -> None:
        cfg = self.cfg
        src = os.path.abspath(cfg.source_file)
        if not os.path.isfile(src):
            raise ParseError(f"source file not found: {src}")
        lines = [f'#include "{os.path.abspath(h)}"' for h in cfg.headers]
        if cfg.prelude_file:
            lines.append(f'#include "{os.path.abspath(cfg.prelude_file)}"')
        lines.append(f'#include "{src}"')
        wrapper = os.path.join(os.path.dirname(src), "__utg_wrapper__.c")
        args = ["-x", "c", "-std=gnu99", "-ffreestanding", "-fno-builtin"]
        if cfg.target:
            args.append(f"--target={cfg.target}")
        args += [f"-I{os.path.abspath(d)}" for d in cfg.include_dirs]
        args += [f"-D{d}" for d in cfg.defines]
        args += list(cfg.extra_flags)
        self.tu = ci.Index.create().parse(
            wrapper, args, unsaved_files=[(wrapper, "\n".join(lines) + "\n")],
            options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        self.src = src
        self.diagnostics = []
        for d in self.tu.diagnostics:
            if d.severity >= 2:
                f = d.location.file
                self.diagnostics.append({
                    "severity": {2: "warning", 3: "error", 4: "fatal"}.get(d.severity, str(d.severity)),
                    "message": d.spelling,
                    "loc": f"{f.name if f else '?'}:{d.location.line}"})

    def _in_source(self, c) -> bool:
        f = c.location.file
        return f is not None and os.path.abspath(f.name) == self.src

    def list_functions(self) -> list:
        if self.tu is None:
            self.parse()
        out = []
        for c in self.tu.cursor.get_children():
            if c.kind == CK.FUNCTION_DECL and c.is_definition() and self._in_source(c):
                args = [(a.spelling, self.conv_type(a.type)) for a in c.get_arguments()]
                out.append({"name": c.spelling, "return_type": c.result_type.spelling,
                            "args": [(n, t.spelling) for n, t in args],
                            "signature": self._signature(c), "line": c.location.line})
        return out

    def _signature(self, c) -> str:
        args = ", ".join(f"{a.type.spelling} {a.spelling}" for a in c.get_arguments()) or "void"
        return f"{c.result_type.spelling} {c.spelling}({args})"

    # -------------------------------------------------------------------------------------------------------
    # types
    # -------------------------------------------------------------------------------------------------------
    def conv_type(self, t) -> TypeInfo:
        canon = t.get_canonical()
        k = canon.kind
        ti = TypeInfo(spelling=t.spelling, canonical=canon.spelling, is_const=t.is_const_qualified())
        if k == TK.BOOL:
            ti.kind, ti.bits, ti.signed = "bool", 8, False
        elif k in _SIGNED or k in _UNSIGNED:
            ti.kind, ti.bits, ti.signed = "int", canon.get_size() * 8, k in _SIGNED
        elif k in (TK.FLOAT, TK.DOUBLE, TK.LONGDOUBLE):
            ti.kind, ti.bits = "float", canon.get_size() * 8
        elif k == TK.ENUM:
            decl = canon.get_declaration()
            u = decl.enum_type.get_canonical()
            ti.kind, ti.bits, ti.signed = "enum", u.get_size() * 8, u.kind in _SIGNED
            ti.enumerators = {e.spelling: e.enum_value for e in decl.get_children()
                              if e.kind == CK.ENUM_CONSTANT_DECL}
        elif k == TK.RECORD:
            ti.kind = "struct"
            ti.fields = [(f.spelling, self.conv_type(f.type)) for f in canon.get_fields()]
        elif k == TK.POINTER:
            ti.kind = "pointer"
        elif k == TK.VOID:
            ti.kind = "void"
        elif k in (TK.INVALID, TK.DEPENDENT, TK.UNEXPOSED):
            ti.kind = "unresolved"
        return ti

    # -------------------------------------------------------------------------------------------------------
    # IR construction
    # -------------------------------------------------------------------------------------------------------
    def build_ir(self, function_name: str) -> FunctionIR:
        if self.tu is None:
            self.parse()
        fn = None
        for c in self.tu.cursor.get_children():
            if c.kind == CK.FUNCTION_DECL and c.is_definition() and c.spelling == function_name \
                    and self._in_source(c):
                fn = c
                break
        if fn is None:
            raise ParseError(f"function '{function_name}' not found in {self.src}")

        self._stmt_id = 0
        self._cond_no = 0
        self._branch_depth = 0
        ir = FunctionIR(
            name=fn.spelling, return_type=self.conv_type(fn.result_type),
            args=[(a.spelling, self.conv_type(a.type)) for a in fn.get_arguments()],
            signature=self._signature(fn), loc=_loc(fn), diagnostics=list(self.diagnostics))
        self.ir = ir
        for n, t in ir.args:
            ir.variables[n] = VarInfo(name=n, type=t, scope="param", is_pointer=(t.kind == "pointer"))
        body = next((k for k in fn.get_children() if k.kind == CK.COMPOUND_STMT), None)
        if body is not None:
            ir.body = self.conv_block(body)
        self._collect_returns(ir.body)
        for e in [d for d in ir.diagnostics if d["severity"] in ("error", "fatal")]:
            self._unsupported("diagnostic", e["loc"], e["message"],
                              "Clang reported an error: parse results may be incomplete.")
        return ir

    def _unsupported(self, kind: str, loc, reason: str, effect: str) -> None:
        entry = {"kind": kind, "loc": str(loc), "reason": reason, "effect": effect}
        if entry not in self.ir.unsupported:
            self.ir.unsupported.append(entry)

    def _collect_returns(self, stmts: list) -> None:
        for s in stmts:
            if s.kind == "return" and s.expr is not None:
                e = s.expr
                while e.kind == "cast" and e.children:
                    e = e.children[0]
                v = e.name if e.kind == "enum_const" else e.value if e.kind == "int_lit" else s.text
                if v not in self.ir.return_values:
                    self.ir.return_values.append(v)
            self._collect_returns(s.then)
            self._collect_returns(s.els)

    # ---------------------------------------------------------------- statements
    def _new_stmt(self, kind: str, c, **kw) -> Stmt:
        self._stmt_id += 1
        return Stmt(id=self._stmt_id, kind=kind, loc=_loc(c), text=self.reader.extent_text(c), **kw)

    def conv_block(self, c) -> list:
        if c.kind == CK.COMPOUND_STMT:
            out: list = []
            for k in c.get_children():
                out += self.conv_block(k)
            return out
        return self.conv_stmt(c)

    def conv_stmt(self, c) -> list:
        k = c.kind
        if k == CK.NULL_STMT:
            return []
        if k == CK.DECL_STMT:
            out = []
            for d in c.get_children():
                if d.kind != CK.VAR_DECL:
                    out.append(self._new_stmt("unsupported", c, note="non-variable declaration"))
                    continue
                vi = self._register_var(d)
                init = None
                kids = [x for x in d.get_children() if x.kind != CK.TYPE_REF]
                if kids:
                    init = self.conv_expr(kids[-1])
                    try:
                        vi.initial_value = evaluate_const(kids[-1])
                    except Exception:  # pragma: no cover
                        pass
                s = self._new_stmt("decl", d, var=d.spelling, expr=init)
                s.text = self.reader.extent_text(d) + ";"
                out.append(s)
            return out
        if k == CK.IF_STMT:
            kids = list(c.get_children())
            cond_expr = self.conv_expr(kids[0])
            self._cond_no += 1
            cid = f"C{self._cond_no}"
            s = self._new_stmt("if", c, expr=cond_expr, cond_id=cid, has_else=len(kids) > 2)
            s.text = "if ( " + self.reader.extent_text(kids[0]) + " )"
            cond = Condition(id=cid, text=self.reader.extent_text(kids[0]), loc=_loc(kids[0]),
                             expr=cond_expr, atoms=[], logical_ops=[], vars=[], true_branch=[],
                             false_branch=[], has_else=len(kids) > 2)
            self._fill_atoms(cond)
            self.ir.conditions.append(cond)
            self._branch_depth += 1
            s.then = self.conv_block(kids[1])
            s.els = self.conv_block(kids[2]) if len(kids) > 2 else []
            self._branch_depth -= 1
            cond.true_branch = [x.text for x in s.then]
            cond.false_branch = [x.text for x in s.els]
            return [s]
        if k == CK.RETURN_STMT:
            kids = list(c.get_children())
            e = self.conv_expr(kids[0]) if kids else None
            return [self._new_stmt("return", c, expr=e)]
        if k.is_expression():
            e = self.conv_expr(c, value_used=False)
            return [self._new_stmt("expr", c, expr=e)]
        reason = f"statement kind {k.name} is not supported by the execution model"
        self._unsupported(k.name, _loc(c), reason,
                          "The function contains this construct; no automatic scenarios are generated for it.")
        return [self._new_stmt("unsupported", c, note=reason)]

    # ---------------------------------------------------------------- variables / calls
    def _register_var(self, ref) -> VarInfo:
        name = ref.spelling
        if name in self.ir.variables:
            return self.ir.variables[name]
        parent = ref.semantic_parent
        if ref.kind == CK.PARM_DECL:
            scope = "param"
        elif parent is not None and parent.kind == CK.FUNCTION_DECL:
            scope = "static" if ref.storage_class == StorageClass.STATIC else "local"
            if scope == "static":
                scope = "static"           # function-local static: persistent state
        else:
            scope = "static" if ref.storage_class == StorageClass.STATIC else "global"
        t = self.conv_type(ref.type)
        vi = VarInfo(name=name, type=t, scope=scope, is_const=t.is_const, decl_loc=_loc(ref),
                     is_pointer=(t.kind == "pointer"))
        if scope in ("global", "static"):
            for k in ref.get_children():
                if k.kind != CK.TYPE_REF:
                    vi.initial_value = evaluate_const(k)
        self.ir.variables[name] = vi
        if t.kind == "unresolved":
            self._unsupported("type", vi.decl_loc, f"type of '{name}' ('{t.spelling}') cannot be resolved",
                              "Variable ignored; declarations are missing (add the header or the prelude).")
        return vi

    def _register_call(self, c, value_used: bool, void_cast: bool, members: Optional[str] = None) -> None:
        name = c.spelling
        decl = c.referenced
        ci_ = self.ir.calls.get(name)
        if ci_ is None:
            params = [(a.spelling, self.conv_type(a.type)) for a in decl.get_arguments()] if decl else []
            ci_ = CallInfo(name=name, return_type=self.conv_type(c.type), params=params, call_sites=[],
                           conditional=True,
                           requires_mock=(decl is None or decl.get_definition() is None),
                           void_cast=void_cast)
            self.ir.calls[name] = ci_
        ci_.call_sites.append(_loc(c))
        if self._branch_depth == 0:
            ci_.conditional = False
        if value_used:
            ci_.return_used = True
        if members and members not in ci_.result_members:
            ci_.result_members.append(members)

    # ---------------------------------------------------------------- expressions
    def _tinfo(self, c) -> TypeInfo:
        return self.conv_type(c.type)

    def _mk(self, kind: str, c, **kw) -> Expr:
        e = Expr(kind=kind, type=self._tinfo(c), text=self.reader.extent_text(c), loc=_loc(c), **kw)
        if e.type.kind == "unresolved":
            self._unsupported("type", e.loc, f"expression '{e.text}' has an unresolved type ('{e.type.spelling}')",
                              "Expression cannot be evaluated; add the missing declaration.")
        return e

    def _unsup_expr(self, c, reason: str) -> Expr:
        self._unsupported(c.kind.name, _loc(c), reason,
                          "Expression cannot be evaluated by the execution model; scenarios involving it are not generated.")
        return self._mk("unsupported", c, name=c.kind.name)

    def _operator(self, c, a, b) -> Optional[str]:
        fa, fb = a.extent.end.file, b.extent.start.file
        if fa is None or fb is None or fa.name != fb.name:
            return None
        s = _strip_noise(self.reader.slice(fa.name, a.extent.end.offset, b.extent.start.offset))
        return s or None

    def conv_expr(self, c, value_used: bool = True) -> Expr:
        k = c.kind
        kids = list(c.get_children())
        if k in (CK.UNEXPOSED_EXPR, CK.PAREN_EXPR):
            if len(kids) != 1:
                return self._unsup_expr(c, f"{k.name} with {len(kids)} children")
            inner = self.conv_expr(kids[0], value_used)
            to = self._tinfo(c)
            if k == CK.UNEXPOSED_EXPR and (to.canonical != inner.type.canonical):
                return Expr(kind="cast", type=to, text=inner.text, loc=inner.loc, implicit=True, children=[inner])
            return inner
        if k == CK.INTEGER_LITERAL or k == CK.CHARACTER_LITERAL:
            v = evaluate_const(c)
            return self._mk("int_lit", c, value=v) if v is not None else self._unsup_expr(c, "literal not evaluable")
        if k == CK.FLOATING_LITERAL:
            v = evaluate_const(c)
            return self._mk("float_lit", c, value=v) if v is not None else self._unsup_expr(c, "literal not evaluable")
        if k == CK.DECL_REF_EXPR:
            r = c.referenced
            if r.kind in (CK.VAR_DECL, CK.PARM_DECL):
                vi = self._register_var(r)
                return self._mk("var_ref", c, name=r.spelling)
            if r.kind == CK.ENUM_CONSTANT_DECL:
                return self._mk("enum_const", c, name=r.spelling, value=r.enum_value)
            return self._unsup_expr(c, f"reference to {r.kind.name}")
        if k == CK.MEMBER_REF_EXPR:
            if len(kids) != 1:
                return self._unsup_expr(c, "member access without base")
            base = self.conv_expr(kids[0], True)
            if base.kind == "call":
                self._register_call_members(base, c.spelling)
            return self._mk("member", c, name=c.spelling, children=[base])
        if k == CK.CALL_EXPR:
            args = [self.conv_expr(a) for a in kids[1:]]
            self._register_call(c, value_used, False)
            return self._mk("call", c, name=c.spelling, children=args)
        if k == CK.CSTYLE_CAST_EXPR:
            operand = kids[-1]
            void_cast = self._tinfo(c).kind == "void"
            inner = self.conv_expr(operand, value_used and not void_cast)
            return self._mk("cast", c, implicit=False, children=[inner])
        if k == CK.CONDITIONAL_OPERATOR and len(kids) == 3:
            return self._mk("cond", c, children=[self.conv_expr(x) for x in kids])
        if k in (CK.BINARY_OPERATOR, CK.COMPOUND_ASSIGNMENT_OPERATOR) and len(kids) == 2:
            op = self._operator(c, kids[0], kids[1])
            if op is None or (op not in _BIN and op not in _ASSIGN):
                v = evaluate_const(c)           # macro-expanded constant expression
                if v is not None:
                    return self._mk("float_lit" if isinstance(v, float) else "int_lit", c, value=v)
                return self._unsup_expr(c, "operator could not be determined")
            lhs, rhs = self.conv_expr(kids[0]), self.conv_expr(kids[1])
            if op == ",":
                return self._unsup_expr(c, "comma operator")
            return self._mk("assign" if op in _ASSIGN else "binary", c, op=op, children=[lhs, rhs])
        if k == CK.UNARY_OPERATOR and len(kids) == 1:
            sk = kids[0]
            s = self.reader
            f = c.extent.start.file
            op, prefix = None, True
            if f is not None and sk.extent.start.file is not None and f.name == sk.extent.start.file.name:
                pre = _strip_noise(s.slice(f.name, c.extent.start.offset, sk.extent.start.offset))
                post = _strip_noise(s.slice(f.name, sk.extent.end.offset, c.extent.end.offset))
                if pre in _UNARY:
                    op, prefix = pre, True
                elif post in ("++", "--"):
                    op, prefix = post, False
            if op is None:
                v = evaluate_const(c)           # e.g. TRUE == (!0) coming from a macro
                if v is not None:
                    return self._mk("float_lit" if isinstance(v, float) else "int_lit", c, value=v)
                return self._unsup_expr(c, "unary operator could not be determined")
            child = self.conv_expr(sk)
            if op in ("++", "--"):
                return self._mk("incdec", c, op=op, prefix=prefix, children=[child])
            return self._mk("unary", c, op=op, children=[child])
        return self._unsup_expr(c, f"expression kind {k.name}")

    def _register_call_members(self, call_expr: Expr, member: str) -> None:
        ci_ = self.ir.calls.get(call_expr.name)
        if ci_ is not None and member not in ci_.result_members:
            ci_.result_members.append(member)

    # ---------------------------------------------------------------- conditions
    def _fill_atoms(self, cond: Condition) -> None:
        def vars_of(e: Expr, acc: list) -> list:
            if e.kind == "var_ref" and e.name not in acc:
                acc.append(e.name)
            for ch in e.children:
                vars_of(ch, acc)
            return acc

        counter = [0]

        def walk(e: Expr) -> None:
            if e.kind == "cast" and e.implicit and e.children:
                return walk(e.children[0])
            if e.kind == "binary" and e.op in ("&&", "||"):
                cond.logical_ops.append(e.op)
                walk(e.children[0])
                walk(e.children[1])
                return
            if e.kind == "unary" and e.op == "!" and e.children:
                return walk(e.children[0])
            counter[0] += 1
            op = e.op if (e.kind == "binary" and e.op in _REL) else None
            cond.atoms.append(Atom(id=f"{cond.id}.a{counter[0]}", text=e.text, op=op, expr=e,
                                   vars=vars_of(e, [])))

        walk(cond.expr)
        cond.vars = vars_of(cond.expr, [])
