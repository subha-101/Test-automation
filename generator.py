import os
import re
import sys
import glob
import json
import shutil
import zipfile
import tempfile
import argparse
import importlib
import pandas as pd

# ===============================
# Existing regex patterns
# ===============================

FUNC_DEF_RE = re.compile(
    r"...",
    re.MULTILINE
)

STATIC_INLINE_RE = re.compile(
    r"...",
    re.MULTILINE
)

# ===============================
# 🔥 ADD YOUR NEW REGEX HERE
# ===============================

# function pointer typedef (ROBUST)
FUNC_PTR_TYPEDEF_RE = re.compile(
    r'''
    typedef\s+
    (?P<ret>[A-Za-z_][\w\s\*]+?)      # return type
    \(\s*\*\s*
    (?P<type>\w+)\s*                  # typedef name
    \)\s*
    \((?P<args>.*?)\)\s*;             # args (multiline safe)
    ''',
    re.MULTILINE | re.VERBOSE | re.DOTALL
)

# extern pointer instance
EXTERN_PTR_RE = re.compile(
    r'''
    extern\s+
    (?P<type>\w+)\s+
    (?P<name>\w+)\s*;
    ''',
    re.MULTILINE | re.VERBOSE
)



INPUT_DIR = "input"
OUTPUT_DIR = ""
INC_DIR = "inc"

first_file = True

TYPEDEF_RE = re.compile(
    r"^\s*typedef\s+(?P<base>[^;]+?)\s+(?P<alias>[A-Za-z_]\w*)\s*;\s*$",
    re.MULTILINE
)

QUALIFIER_TOKENS = {
    "const", "volatile", "register", "static", "extern", "restrict", "signed", "unsigned"
}

# -------------------------------------------------
# Find first .c file automatically
# -------------------------------------------------
def find_c_file():
    if not os.path.exists(INPUT_DIR):
        return None

    for file in os.listdir(INPUT_DIR):
        if file.endswith(".c"):
            return os.path.join(INPUT_DIR, file)
    return None


def get_project_root():
    """
    Resolve project root from this script location:
    tools/auto_test_tool/generator.py -> project root is two levels up.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(script_dir, "..", ".."))


def find_source_file(source_arg, search_root):
    """
    Resolve a C source file from a CLI argument.

    Supported input:
    - absolute path to a .c file
    - relative path to a .c file
    - bare filename (with or without .c), searched recursively in search_root
    """
    if not source_arg:
        return None

    source_arg = source_arg.strip()

    # direct path (absolute or relative)
    direct_candidate = source_arg
    if os.path.exists(direct_candidate) and os.path.isfile(direct_candidate):
        return os.path.abspath(direct_candidate)

    relative_candidate = os.path.join(search_root, source_arg)
    if os.path.exists(relative_candidate) and os.path.isfile(relative_candidate):
        return os.path.abspath(relative_candidate)

    # filename search
    target_names = {os.path.basename(source_arg).lower()}
    if not source_arg.lower().endswith(".c"):
        target_names.add(f"{os.path.basename(source_arg).lower()}.c")

    matches = []
    for root, _, files in os.walk(search_root):
        for file_name in files:
            if file_name.lower() in target_names:
                matches.append(os.path.join(root, file_name))

    if not matches:
        return None

    if len(matches) == 1:
        return os.path.abspath(matches[0])

    print("ERROR: Multiple source files matched your input. Be more specific:")
    for m in sorted(matches):
        print(f"  - {m}")
    return None


def split_params(params_text):
    """
    Split parameter list by commas while respecting nested parentheses.
    """
    params_text = params_text.strip()
    if not params_text or params_text == "void":
        return []

    parts = []
    current = []
    depth = 0

    for ch in params_text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1

        if ch == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue

        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)

    return parts


def load_type_aliases(type_header_paths):
    """
    Build a typedef alias map from one or more headers.
    """
    aliases = {}

    for header_path in type_header_paths:
        if not os.path.exists(header_path):
            continue

        with open(header_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

        for match in TYPEDEF_RE.finditer(text):
            base = re.sub(r"\s+", " ", match.group("base")).strip()
            alias = match.group("alias").strip()
            aliases[alias] = base

    return aliases


def normalize_type_token(type_text):
    """
    Return the likely root type token from a declaration fragment.
    """
    cleaned = re.sub(r"\s+", " ", type_text.strip())
    cleaned = cleaned.replace("*", " ")
    cleaned = re.sub(r"\[[^\]]*\]", " ", cleaned)
    tokens = [t for t in cleaned.split() if t and t.lower() not in QUALIFIER_TOKENS]
    if not tokens:
        return ""
    return tokens[-1]


def resolve_alias_token(token, aliases, depth=0):
    """
    Resolve typedef alias chains, with a small recursion guard.
    """
    if not token or token not in aliases or depth > 8:
        return token

    next_token = normalize_type_token(aliases[token])
    if not next_token or next_token == token:
        return token

    return resolve_alias_token(next_token, aliases, depth + 1)


def default_value_for_type(type_text, array_suffix="", type_aliases=None):
    """
    Provide a default initializer based on a C-like type.
    """
    t = re.sub(r"\s+", " ", type_text.strip()).lower()
    type_aliases = type_aliases or {}

    if array_suffix:
        return "{0}"

    if "*" in type_text:
        return "NULL"

    root_token = normalize_type_token(type_text)
    resolved_token = resolve_alias_token(root_token, type_aliases)
    root_l = root_token.lower() if root_token else ""
    resolved_l = resolved_token.lower() if resolved_token else ""

    if root_l == "bo" or resolved_l == "bo":
        return "FALSE"

    float_tokens = {
        "float", "double", "f32", "f64"
    }
    int_tokens = {
        "char", "short", "int", "long", "signed", "unsigned",
        "size_t", "ptrdiff_t", "u8", "u16", "u32", "u64",
        "s8", "s16", "s32", "s64"
    }
    bool_tokens = {"bool", "boolean", "bo"}

    if any(token in t for token in bool_tokens):
        return "false"
    if any(token in t for token in float_tokens) or resolved_l in float_tokens:
        return "0.0"
    if any(token in t for token in int_tokens) or resolved_l in int_tokens:
        return "0"

    return "0"


def parse_function_arguments(params_text, type_aliases=None):
    """
    Parse function parameter text into [{"type", "name", "default"}, ...].
    """
    # Remove comments from signature params so inline docs do not break parsing.
    clean_params_text = re.sub(r"/\*.*?\*/", " ", params_text, flags=re.DOTALL)
    clean_params_text = re.sub(r"//.*?$", " ", clean_params_text, flags=re.MULTILINE)
    params = split_params(clean_params_text)
    parsed = []

    for idx, param in enumerate(params, start=1):
        p = re.sub(r"\s+", " ", param.strip())
        if not p or p == "void" or p == "...":
            continue
        # VO / V O is a project typedef for void — treat as no parameter
        if re.sub(r"\s+", "", p) in ("VO", "V"):
            continue

        # function-pointer parameter, e.g. void (*cb)(int)
        fp_match = re.match(r"^(?P<prefix>.*?)\(\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)(?P<suffix>.*)$", p)
        if fp_match:
            name = fp_match.group("name")
            param_type = (
                f"{fp_match.group('prefix').strip()} (*){fp_match.group('suffix').strip()}"
            ).strip()
            parsed.append({
                "type": param_type,
                "name": name,
                "default": "NULL"
            })
            continue

        array_suffix = ""
        arr_match = re.match(r"^(?P<base>.*?)(?P<array>\[[^\]]*\])$", p)
        if arr_match:
            p = arr_match.group("base").strip()
            array_suffix = arr_match.group("array")

        m = re.match(r"^(?P<type>.+?)\s*(?P<name>[A-Za-z_]\w*)$", p)
        if m:
            param_type = m.group("type").strip()
            name = m.group("name").strip()
        else:
            # unnamed parameter fallback
            param_type = p
            name = f"arg{idx}"

        parsed.append({
            "type": param_type,
            "name": name,
            "array": array_suffix,
            "default": default_value_for_type(param_type, array_suffix, type_aliases)
        })

    return parsed


# -------------------------------------------------
# Step 1: Robust function parser (FIXED)
# -------------------------------------------------
def extract_functions(code, type_aliases=None):
    """
    Robust C function detector.
    """

    C_KEYWORDS = {
        "if", "while", "for", "switch", "return",
        "sizeof", "else", "do", "case"
    }

    pattern = re.compile(
        r'''
        ^\s*
        (?:static\s+)?              # optional static
        (?:inline\s+)?              # optional inline
        ([A-Za-z_][\w\s\*\(\)]*?)   # return type
        \s+
        ([A-Za-z_]\w+)              # function name
        \s*
        \(([^;{}()]*)\)             # params
        \s*
        \{                          # must have body
        ''',
        re.MULTILINE | re.VERBOSE
    )

    functions = []

    for ret, name, params in pattern.findall(code):

        name = name.strip()

        # 🔥 CRITICAL FILTERS
        if name in C_KEYWORDS:
            continue
        if name.startswith("_"):
            continue

        parsed_args = parse_function_arguments(params, type_aliases)

        functions.append({
            "return": ret.strip(),
            "name": name,
            "params": params.strip(),
            "args": parsed_args
        })

    return functions

# -------------------------------------------------
# Step 1B: Detect UNIT_TESTING function pointers
# -------------------------------------------------
def extract_test_pointers(code):
    """
    Robust UNIT_TESTING pointer detector.

    Detects patterns like:

        typedef BO (*spv_app_joy_mixed_ptr)(F32 a, F32 b);
        extern spv_app_joy_mixed_ptr get_spv_app_joy_mixed_ptr;
    """

    # normalize newlines
    code = code.replace("\r\n", "\n")

    # ---------------------------------------------
    # STEP 1 — typedef function pointers
    # ---------------------------------------------
    typedef_pattern = re.compile(
        r'''
        typedef\s+
        ([A-Za-z_][\w\s\*]+?)      # return type
        \(\s*\*\s*
        (\w+_ptr)                  # pointer typedef name
        \s*\)\s*
        \((.*?)\)                  # parameters (lazy, multiline safe)
        \s*;
        ''',
        re.VERBOSE | re.MULTILINE | re.DOTALL
    )

    # ---------------------------------------------
    # STEP 2 — extern getters
    # ---------------------------------------------
    getter_pattern = re.compile(
        r'''
        extern\s+
        (\w+_ptr)\s+               # typedef name
        (get_\w+_ptr)\s*;          # getter name
        ''',
        re.VERBOSE | re.MULTILINE
    )

    typedefs = {}
    pointers = {}

    # ---------------------------------------------
    # collect typedefs
    # ---------------------------------------------
    for ret_type, typedef_name, params in typedef_pattern.findall(code):

        base_func = typedef_name.replace("_ptr", "")

        typedefs[typedef_name] = {
            "return": ret_type.strip(),
            "func": base_func,
            "params": params.strip(),
        }

    # ---------------------------------------------
    # match getters
    # ---------------------------------------------
    for ptr_type, getter in getter_pattern.findall(code):

        if ptr_type in typedefs:
            base_func = typedefs[ptr_type]["func"]

            pointers[base_func] = {
                "getter": getter,
                "typedef": ptr_type,
                "return": typedefs[ptr_type]["return"],
                "params": typedefs[ptr_type]["params"],
            }

    return pointers


# -------------------------------------------------
# Step 2: Detect external calls (cleaned)
# -------------------------------------------------
def extract_external_calls(code):
    calls = set()

    call_pattern = r'\b(\w+)\s*\('
    all_calls = re.findall(call_pattern, code)

    ignore = {
        "if", "while", "switch", "return",
        "sizeof", "for"
    }

    for c in all_calls:
        if c not in ignore:
            calls.add(c)

    return sorted(list(calls))


def strip_c_comments(text):
    """Remove C and C++ comments from text."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//.*?$", " ", text, flags=re.MULTILINE)
    return text


def extract_function_declarations_from_headers(header_files):
    """
    Parse function declarations from header files and return:
      name -> {"return": str, "name": str, "params": str}
    """
    decls = {}
    decl_re = re.compile(
        r'''
        ^\s*
        (?!typedef\b)
        (?P<ret>[A-Za-z_][\w\s\*\(\)]*?)
        \s+
        (?P<name>[A-Za-z_]\w*)
        \s*
        \((?P<params>[^;{}]*)\)
        \s*;
        ''',
        re.MULTILINE | re.VERBOSE | re.DOTALL,
    )

    for hdr in header_files:
        try:
            with open(hdr, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue

        text = strip_c_comments(text)

        for m in decl_re.finditer(text):
            ret = re.sub(r"\s+", " ", m.group("ret").strip())
            name = m.group("name").strip()
            params = re.sub(r"\s+", " ", m.group("params").strip())

            if name.startswith("get_") and name.endswith("_ptr"):
                continue
            if name in decls:
                continue

            decls[name] = {
                "return": ret,
                "name": name,
                "params": params if params else "void",
            }

    return decls


def resolve_dependency_declarations(code, functions, static_funcs, declaration_map):
    """
    Find external function calls not defined in the current source file and
    resolve their declarations from headers.
    """
    called_names = set(extract_external_calls(code))
    local_names = {f["name"] for f in functions}
    static_names = {f["name"] for f in static_funcs}

    unresolved = sorted(
        name for name in called_names
        if name not in local_names and name not in static_names
    )

    resolved = []
    unresolved_missing_decl = []
    for name in unresolved:
        decl = declaration_map.get(name)
        if decl:
            resolved.append(decl)
        else:
            unresolved_missing_decl.append(name)

    return resolved, unresolved_missing_decl


# Pattern 1: TYPE varname = funcname();  — type declared on same line
_ASSIGN_CALL_RE = re.compile(
    r"^\s*"
    r"(?P<type>[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*?)"
    r"\s+[A-Za-z_]\w*"
    r"\s*=\s*"
    r"(?P<func>[A-Za-z_]\w*)"
    r"\s*\(\s*\)"
    r"\s*;",
    re.MULTILINE,
)

# Pattern 2: varname = funcname();  — var declared elsewhere, look up its type
_PLAIN_ASSIGN_CALL_RE = re.compile(
    r"^\s*"
    r"(?P<var>[A-Za-z_]\w*)"
    r"\s*=\s*"
    r"(?P<func>[A-Za-z_]\w*)"
    r"\s*\(\s*\)"
    r"\s*;",
    re.MULTILINE,
)

# Pattern 3: (RETTYPE) funcname(arg1, arg2, ...);  — cast-prefixed void call
_CAST_CALL_RE = re.compile(
    r"^\s*"
    r"\(\s*(?P<ret>[A-Za-z_]\w*)\s*\)"
    r"\s*(?P<func>[A-Za-z_]\w*)"
    r"\s*\((?P<args>[^)]*)\)"
    r"\s*;",
    re.MULTILINE,
)

# Variable declarations: [static] TYPE varname [= | ;]
_VAR_DECL_RE = re.compile(
    r"^\s*(?:static\s+)?"
    r"(?P<type>[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*?)"
    r"\s+(?P<var>[A-Za-z_]\w*)"
    r"\s*(?:[=;])",
    re.MULTILINE,
)


def _build_var_type_map(code: str) -> dict:
    """Return a {varname: declared_type} map built from the source."""
    var_map: dict = {}
    clean = strip_c_comments(code)
    for m in _VAR_DECL_RE.finditer(clean):
        var = m.group("var").strip()
        typ = re.sub(r"\s+", " ", m.group("type").strip())
        if var not in var_map:
            var_map[var] = typ
    return var_map


def _infer_params_from_args(raw_args: str, var_type_map: dict) -> str:
    """
    Turn a raw argument list string into a typed parameter declaration string.
    Each simple-identifier argument is looked up in var_type_map; unknowns
    fall back to 'int'.
    """
    if not raw_args.strip():
        return "void"
    parts = []
    for arg in raw_args.split(","):
        arg = arg.strip()
        if not arg:
            continue
        # Strip any leading (TYPE) cast on the argument itself
        cast_m = re.match(r"^\(\s*[A-Za-z_]\w*\s*\)\s*(.+)$", arg)
        if cast_m:
            arg = cast_m.group(1).strip()
        if re.match(r"^[A-Za-z_]\w*$", arg):
            typ = var_type_map.get(arg, "int")
            parts.append(f"{typ} {arg}")
        else:
            parts.append(f"int /* {arg} */")
    return ", ".join(parts) if parts else "void"


def infer_macro_function_stubs(code, missing_names):
    """
    For each name in *missing_names* (macro-defined functions with no header
    declaration), scan the source for one of three usage patterns and
    synthesise a stub declaration.

    Pattern 1 — typed declaration:    TYPE var = funcname();
    Pattern 2 — plain assignment:     var = funcname();        (type from decl map)
    Pattern 3 — cast-prefixed call:   (RETTYPE) funcname(args);
    """
    clean = strip_c_comments(code)
    var_type_map = _build_var_type_map(code)

    # name → (return_type, params_string)
    inferred: dict = {}

    # Pattern 1
    for m in _ASSIGN_CALL_RE.finditer(clean):
        func = m.group("func").strip()
        ret  = re.sub(r"\s+", " ", m.group("type").strip())
        if func not in inferred:
            inferred[func] = (ret, "void")

    # Pattern 2
    for m in _PLAIN_ASSIGN_CALL_RE.finditer(clean):
        func = m.group("func").strip()
        var  = m.group("var").strip()
        if func not in inferred:
            ret = var_type_map.get(var)
            if ret:
                inferred[func] = (ret, "void")

    # Pattern 3
    for m in _CAST_CALL_RE.finditer(clean):
        func     = m.group("func").strip()
        ret      = re.sub(r"\s+", " ", m.group("ret").strip())
        raw_args = m.group("args").strip()
        if func not in inferred:
            params = _infer_params_from_args(raw_args, var_type_map)
            inferred[func] = (ret, params)

    stubs = []
    for name in missing_names:
        entry = inferred.get(name)
        if entry:
            ret, params = entry
            stubs.append({"return": ret, "name": name, "params": params})
            print(f"  [macro stub] inferred: {ret} {name}({params})")

    return stubs


def parse_stub_arguments(params_text):
    """Parse declaration parameter list for stub generation."""
    params = (params_text or "").strip()
    if not params or params in {"void", "VO"}:
        return []
    return parse_function_arguments(params)


def mock_return_line(return_type, type_aliases=None):
    """Create return statement based on return type for C mock stubs."""
    type_aliases = type_aliases or {}
    rt = _strip_static_qualifiers(return_type).strip()
    rt_lower = rt.lower()

    if rt_lower in {"void", "vo"}:
        return None

    if "*" in rt:
        return f"    return ({rt})mock_c()->returnValue().value.pointerValue;"

    root = normalize_type_token(rt)
    resolved = resolve_alias_token(root, type_aliases)
    root_l = root.lower() if root else ""
    resolved_l = resolved.lower() if resolved else ""

    if root_l in {"bo", "bool", "boolean"} or resolved_l in {"bo", "bool", "boolean"}:
        return f"    return ({rt})mock_c()->returnIntValueOrDefault(0);"

    float_tokens = {"float", "double", "f32", "f64"}
    if root_l in float_tokens or resolved_l in float_tokens or any(t in rt_lower for t in float_tokens):
        return f"    return ({rt})mock_c()->returnDoubleValueOrDefault(0.0f);"

    int_tokens = {
        "char", "short", "int", "long", "signed", "unsigned",
        "size_t", "ptrdiff_t", "u8", "u16", "u32", "u64",
        "s8", "s16", "s32", "s64", "rc"
    }
    if root_l in int_tokens or resolved_l in int_tokens or resolved_l.endswith("_e"):
        return f"    return ({rt})mock_c()->returnIntValueOrDefault(0);"

    # Fallback for unknown scalar-ish typedefs/enums.
    return f"    return ({rt})mock_c()->returnIntValueOrDefault(0);"


def render_dependency_stub(decl, type_aliases=None):
    """Render one dependency declaration and corresponding C stub body."""
    ret = decl["return"].strip()
    name = decl["name"].strip()
    params = decl["params"].strip() or "void"

    header_decl = f"{ret} {name}({params});"

    body_lines = [
        f"{ret} {name}({params})",
        "{",
    ]

    for arg in parse_stub_arguments(params):
        body_lines.append(f"    (void){arg['name']};")

    body_lines.append(f'    mock_c()->actualCall("{name}");')
    ret_line = mock_return_line(ret, type_aliases)
    if ret_line:
        body_lines.append(ret_line)

    body_lines.append("}")

    return header_decl, "\n".join(body_lines)


# -------------------------------------------------
# Step 3A: Load TESSY JSON for a function (if present)
# -------------------------------------------------
def load_tessy_json(json_dir, func_name):
    """
    Try to locate a TESSY-extracted JSON file for *func_name* inside
    *json_dir*.  Returns the parsed dict, or None if not found.

    The JSON file is expected to be named  <func_name>.json  (exactly
    the name the tessy_parser engine writes).
    """
    if not json_dir or not os.path.isdir(json_dir):
        return None

    candidate = os.path.join(json_dir, f"{func_name}.json")
    if not os.path.isfile(candidate):
        return None

    try:
        with open(candidate, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"  [TESSY JSON] Loaded: {candidate}")
        return data
    except (json.JSONDecodeError, IOError) as exc:
        print(f"  [TESSY JSON] WARNING: Could not read {candidate}: {exc}")
        return None


# -------------------------------------------------
# Step 3B: Render one TEST(...) block from JSON data
# -------------------------------------------------
def _format_value_for_cpp(value):
    """
    Convert a Python value (int, float, bool, str) to a C/C++ literal.
    """
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        literal = f"{value}"
        if "." in literal:
            return f"{literal}f"
        return literal
    if isinstance(value, str):
        upper = value.strip().upper()
        if upper in {"TRUE", "TRUE_VAL", "1"}:
            return "TRUE"
        if upper in {"FALSE", "FALSE_VAL", "0"}:
            return "FALSE"
        if upper == "NULL":
            return "NULL"
        text = value.strip()
        decimal_number_re = re.compile(
            r"^[+-]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?[fF]?$"
        )
        if decimal_number_re.match(text):
            if text.endswith(("f", "F")):
                return text
            return f"{text}f"
        return value
    return str(value)


# Qualifiers that can appear as a leading token in the return-type string
# when the function was declared STATIC_INLINE / STATIC_IN_APP / static.
_STATIC_QUALIFIER_RE = re.compile(
    r"^(?:static\s+(?:inline\s+)?|STATIC_INLINE\s+|STATIC_IN_APP\s+|STATIC\s+)",
    re.IGNORECASE,
)


def _strip_static_qualifiers(return_type: str) -> str:
    """Remove leading static/inline qualifier macros from a C return type string."""
    return _STATIC_QUALIFIER_RE.sub("", return_type).strip()


def _bare_pointee_type(type_text: str) -> str:
    """
    Derive the underlying object type from a pointer type declaration.

    Strips all pointer declarators ('*') and const/volatile qualifiers so
    that we get a plain struct/typedef name suitable for declaring the local
    backing variable of a target_ argument.

    Examples
    --------
      const trala_data_mast_param_1_t * const  →  trala_data_mast_param_1_t
      cspecs_mast_parameter_t *               →  cspecs_mast_parameter_t
      const uint8_t *                          →  uint8_t
      uint32_t * const                         →  uint32_t
      my_struct_t **                           →  my_struct_t
    """
    t = type_text.strip().replace("*", " ")
    t = re.sub(r"\bconst\b",    "", t)
    t = re.sub(r"\bvolatile\b", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _make_const_pointer_type(orig_type: str) -> str:
    """
    Ensure the pointer itself is declared const.

    When we initialise a pointer argument with the address of a local
    backing variable, the pointer should not be reassigned inside the test.
    This function appends '* const' after the last '*' unless the pointer
    is already const.

    Examples
    --------
      'T *'                   →  'T * const'
      'T * const'             →  'T * const'         (unchanged)
      'const T * const'       →  'const T * const'   (unchanged)
    """
    t = orig_type.strip()
    # Check the fragment after the last '*'
    after_last_star = t.rsplit("*", 1)[-1].strip()
    if "const" in after_last_star.split():
        return t          # already a const pointer — leave as-is
    idx = t.rfind("*")
    return t[:idx + 1] + " const" + t[idx + 1:]


def default_init_value_for_return_type(clean_return, type_aliases=None):
    """Map a function return type to a default C/C++ literal value."""
    type_aliases = type_aliases or {}
    rt = _strip_static_qualifiers(clean_return or "").strip()
    rt_lower = rt.lower()

    if not rt or rt_lower in {"void", "vo"}:
        return "0"

    if "*" in rt:
        return "NULL"

    root = normalize_type_token(rt)
    resolved = resolve_alias_token(root, type_aliases)
    root_l = root.lower() if root else ""
    resolved_l = resolved.lower() if resolved else ""

    bool_tokens = {"bo", "bool", "boolean"}
    float_tokens = {"float", "f32"}
    double_tokens = {"double", "f64"}
    int_tokens = {
        "char", "short", "int", "long", "signed", "unsigned",
        "size_t", "ptrdiff_t", "u8", "u16", "u32", "u64",
        "s8", "s16", "s32", "s64", "rc"
    }

    if root_l in bool_tokens or resolved_l in bool_tokens:
        return "FALSE"
    if root_l in float_tokens or resolved_l in float_tokens:
        return "0.0f"
    if root_l in double_tokens or resolved_l in double_tokens:
        return "0.0"
    if root_l in int_tokens or resolved_l in int_tokens:
        return "0"
    if root_l.endswith("_e") or resolved_l.endswith("_e"):
        return "0"

    return "0"

def _is_function_pointer_list_type(type_text: str) -> bool:
    """Return True for typedef-backed function pointer list parameters."""
    compact = re.sub(r"\s+", " ", (type_text or "")).strip()
    return bool(
        re.search(r"\b\w+(?:_func_t|_fct_t)\b\s*\*\s*(?:const\s*)?\*", compact)
    )


def _split_function_pointer_values(raw_value):
    """Split a JSON value into function names for pointer-list initialization."""
    if isinstance(raw_value, list):
        candidates = raw_value
    else:
        text = str(raw_value or "").strip()
        if not text:
            return []
        candidates = re.split(r"[\s,{}]+", text)

    values = []
    for candidate in candidates:
        token = str(candidate).strip()
        if token and token != "NULL":
            values.append(token)
    return values


def _render_function_pointer_list_declaration(arg, value):
    """Render declarations for a function-pointer-list argument."""
    func_names = _split_function_pointer_values(value)
    if not func_names:
        func_names = ["NULL"]
    elif func_names[-1] != "NULL":
        func_names.append("NULL")

    element_type = re.sub(r"\s*\*\s*$", "", re.sub(r"\s+", " ", arg["type"]).strip())
    storage_name = f"{arg['name']}_values"
    lines = [
        f"    {element_type} {storage_name}[] = {{ {', '.join(func_names)} }};",
        f"    {arg['type']} {arg['name']} = {storage_name};",
    ]
    return lines

def _json_variable_base_name(name: str) -> str:
    """Return a clean C variable name from a JSON variable/check name."""
    clean_name = str(name or "").strip()
    clean_name = clean_name.split("=", 1)[0].strip()
    clean_name = clean_name.lstrip("*").strip()
    if clean_name.startswith("p_"):
        clean_name = clean_name[2:]
    return clean_name


def _pointer_name_for_json_variable(name: str) -> str:
    """Return the UNIT_TESTING pointer name used for a JSON variable."""
    return f"p_{_json_variable_base_name(name)}"


def _pointer_assignment_for_json_variable(name: str, value: str) -> str:
    """Render a JSON variable assignment through its UNIT_TESTING pointer."""
    return f"    *{_pointer_name_for_json_variable(name)} = {value};"


def collect_json_function_argument_pointers(tessy_data, func, var_type_map=None):
    """Collect unique function_argument pointer declarations needed by JSON tests."""
    if not tessy_data:
        return []

    arg_types = {arg["name"]: arg["type"] for arg in func.get("args", [])}
    var_type_map = var_type_map or {}
    pointers = []
    seen = set()

    for tc in tessy_data.get("testcases", []):
        for section in ("inputs", "outputs"):
            for item in tc.get(section, []):
                item_type = item.get("type")
                if item_type != "function_argument" and not (section == "outputs" and item_type == "global_variable_check"):
                    continue
                name = _json_variable_base_name(item.get("name", ""))
                if not name or name in seen:
                    continue
                if re.match(r"^target_\w+\.\w+$", name):
                    continue

                pointers.append({
                    "type": arg_types.get(name) or var_type_map.get(name),
                    "name": _pointer_name_for_json_variable(name),
                    "source": name,
                })
                seen.add(name)

    return pointers

def _doxygen_test_comment(tc, function_name, test_name):
    """Return a Doxygen block documenting one test case dict from TESSY JSON."""
    inputs = tc.get("inputs", []) if isinstance(tc, dict) else []
    outputs = tc.get("outputs", []) if isinstance(tc, dict) else []
    call_trace = tc.get("call_trace", []) if isinstance(tc, dict) else []
    description = (tc.get("description", "") if isinstance(tc, dict) else "").strip()

    lines = ["/**"]

    if description:
        brief = f"Validate {function_name}() - {description}."
    elif outputs:
        brief = f"Validate {function_name}() returns expected output."
    elif call_trace:
        brief = f"Validate {function_name}() calls expected dependencies."
    else:
        brief = f"Validate {function_name}() behavior."

    lines.append(f" * \\brief {brief}")
    lines.append(f" * \\test {test_name}")
    lines.append(" * \\pre Inputs:")

    if inputs:
        for inp in inputs:
            inp_type = inp.get("type", "")
            if inp_type == "mock_return":
                ret_val = _format_value_for_cpp(inp.get("return_value", 0))
                lines.append(
                    f" * - {inp.get('function', 'unknown_function')}() mocked return = {ret_val}."
                )
            elif inp_type == "mock_struct_return":
                member = inp.get("member", "member")
                mval = _format_value_for_cpp(inp.get("value", 0))
                lines.append(
                    f" * - {inp.get('function', 'unknown_function')}() mocked struct return has .{member} = {mval}."
                )
            else:
                name = inp.get("name", "input")
                value = _format_value_for_cpp(inp.get("value", 0))
                lines.append(f" * - {name} = {value}.")
    else:
        lines.append(" * - None.")

    lines.append(" * \\post Expected output:")
    has_expected = bool(outputs) or bool(call_trace)

    if has_expected:
        for out in outputs:
            out_type = out.get("type", "")
            expected = _format_value_for_cpp(out.get("expected_value", 0))

            if out_type == "return_value_check":
                lines.append(f" * - return_value = {expected}.")
            elif out_type == "global_variable_check":
                out_name = out.get("name", "global_variable")
                # Skip mis-reported checks where the "variable" is actually
                # the function under test's own name.
                if out_name == function_name:
                    continue
                lines.append(f" * - {out_name} = {expected}.")
            else:
                out_name = out.get("name", "output")
                lines.append(f" * - {out_name} = {expected}.")

        call_counts: dict[str, int] = {}
        for ct in call_trace:
            func = ct.get("function", "unknown_function")
            call_counts[func] = call_counts.get(func, 0) + ct.get("count", 1)

        for func, count in call_counts.items():
            lines.append(
                f" * - {func}() called {count} time(s)."
            )
    else:
        lines.append(" * - None.")

    lines.append(" */")
    return "\n".join(lines)

def generate_test_body_from_json(tc, func, call_expr):
    """
    Generate the body lines of one TEST(...) block from a TESSY test case dict.

    Parameters
    ----------
    tc : dict
        One element of ``testcases`` from the TESSY JSON.
    func : dict
        The function dict produced by ``extract_functions()``
        (keys: return, name, params, args).
    call_expr : str
        The full call expression string (e.g. ``mcal_master_io_pull_key_switch_on()``).

    Returns
    -------
    list[str]
        Lines to write inside the TEST { } block, without outer braces.
    """
    # Each section is built independently and joined with a single blank
    # line between any two non-empty sections (inputs / mocks / call /
    # assertions / checkExpectations), for readability.
    input_lines  = []
    mock_lines   = []
    call_lines   = []
    output_lines = []

    inputs       = tc.get("inputs", [])
    outputs      = tc.get("outputs", [])
    call_trace   = tc.get("call_trace", [])
    args         = func.get("args", [])

    # -------------------------------------------------------------------
    # 1. Declare local variables for direct function arguments
    #
    # Three sub-cases for function_argument inputs:
    #
    # (a) MEMBER ASSIGNMENT on a target_ backing variable
    #     name  = "target_p_data.height",  value = 100
    #     → deferred until after all variable declarations:
    #       target_p_data.height = 100;
    #
    # (b) TARGET-BACKED POINTER argument
    #     name  = "p_data",  value = "target_p_data"
    #     The formal argument is a pointer; we must first declare a local
    #     struct/object of the pointed-to type, then initialise the pointer
    #     argument with its address:
    #       <bare_type>   target_p_data;
    #       <const_ptr_t> p_data = &target_p_data;
    #
    # (c) PLAIN SCALAR OVERRIDE
    #     name = "speed",  value = 100
    #     → <type> speed = 100;
    # -------------------------------------------------------------------

    arg_map = {a["name"]: a for a in args}  # formal name → arg dict

    # First pass: scan all function_argument inputs and classify them
    target_backed     = {}   # formal_arg_name  → target_var_name  (case b)
    member_assignments = []  # deferred "target_X.member = val;" lines  (case a)
    arg_overrides     = {}   # formal_arg_name  → literal value          (case c)

    for inp in inputs:
        if inp.get("type") != "function_argument":
            continue

        name      = inp.get("name", "").strip()
        raw_value = inp.get("value", 0)
        value_str = _format_value_for_cpp(raw_value)

        # ── Case (a): member assignment  target_X.member ──────────────
        if re.match(r"^target_\w+\.\w+$", name):
            member_assignments.append(f"    {name} = {value_str};")
            continue

        # ── Case (b): target-backed pointer argument ───────────────────
        if isinstance(raw_value, str) and raw_value.strip().startswith("target_"):
            if name in arg_map:
                target_backed[name] = raw_value.strip()
            # else: unknown arg name — skip silently
            continue

        # ── Case (c): plain scalar / non-pointer override ─────────────
        if name in arg_map:
            arg_overrides[name] = value_str

    # Second pass: emit declarations in formal-argument order so that the
    # output always respects the function signature top-to-bottom.
    pre_call_target_lines = []   # target var + pointer arg declarations
    pre_call_plain_lines  = []   # scalar arg declarations

    for arg in args:
        aname = arg["name"]

        if _is_function_pointer_list_type(arg["type"]):
            # Function-pointer-list args use their own renderer (unchanged)
            val = arg_overrides.get(aname, arg.get("default", "NULL"))
            pre_call_plain_lines.extend(
                _render_function_pointer_list_declaration(arg, val)
            )

        elif aname in target_backed:
            # Case (b): emit backing variable then const-pointer arg,
            # PAIRED together so they appear adjacent in the test body.
            target_var     = target_backed[aname]
            bare_type      = _bare_pointee_type(arg["type"])
            const_ptr_type = _make_const_pointer_type(arg["type"])
            pre_call_target_lines.append(f"    {bare_type} {target_var};")
            pre_call_target_lines.append(
                f"    {const_ptr_type} {aname} = &{target_var};"
            )

        elif aname in arg_overrides:
            # Case (c): plain override
            val = arg_overrides[aname]
            if arg.get("array"):
                pre_call_plain_lines.append(
                    f"    {arg['type']} {aname}{arg['array']} = {arg.get('default', '0')};"
                )
                pre_call_plain_lines.append(_pointer_assignment_for_json_variable(aname, val))
            else:
                pre_call_plain_lines.append(f"    {arg['type']} {aname} = {arg.get('default', '0')};")
                pre_call_plain_lines.append(_pointer_assignment_for_json_variable(aname, val))

        else:
            # No override — use the default value from the function signature
            default_val = arg.get("default", "0")
            if arg.get("array"):
                pre_call_plain_lines.append(
                    f"    {arg['type']} {aname}{arg['array']} = {default_val};"
                )
            else:
                pre_call_plain_lines.append(
                    f"    {arg['type']} {aname} = {default_val};"
                )

    # Emit: target-backed pairs first (they carry the most structure),
    # then plain scalars, then member assignments.
    input_lines.extend(pre_call_target_lines)
    input_lines.extend(pre_call_plain_lines)

    # Member assignments come after ALL variable declarations so that the
    # target backing variables exist when the assignments are executed.
    input_lines.extend(member_assignments)

    # Legacy non-arg "function_argument" entries that don't correspond to
    # any formal parameter (e.g. global state setters encoded in the JSON).
    # These are emitted as plain assignments just before the call.
    for inp in inputs:
        if inp.get("type") != "function_argument":
            continue
        name      = inp.get("name", "").strip()
        raw_value = inp.get("value", 0)
        value_str = _format_value_for_cpp(raw_value)
        # Skip already-handled cases
        if re.match(r"^target_\w+\.\w+$", name):
            continue
        if isinstance(raw_value, str) and raw_value.strip().startswith("target_"):
            continue
        if name in arg_map:
            continue
        # Genuine unknown assignment
        input_lines.append(_pointer_assignment_for_json_variable(name, value_str))

    # -------------------------------------------------------------------
    # 2. mock().expectOneCall / expectNCalls for call_trace (count > 1)
    #    combined with andReturnValue for mock_return inputs.
    #
    # RULE: The call_trace table is the authoritative source for WHICH
    # functions must be verified.  A mock_return input whose function is
    # NOT in the call_trace table means TESSY recorded a return value for
    # setup purposes but the function is not expected to be called in this
    # test case (e.g. it exits before reaching that call).  Such inputs
    # must be silently dropped — no expectation is generated for them.
    # -------------------------------------------------------------------

    # Step 2a: build call-count lookup from call_trace (authoritative set)
    call_counts: dict[str, int] = {}
    for ct in call_trace:
        func_name = ct["function"]
        # Accumulate counts when the same function appears multiple times
        call_counts[func_name] = call_counts.get(func_name, 0) + ct.get("count", 1)

    # Step 2b: build return-value lookup from mock_return inputs,
    # but ONLY for functions that are present in call_counts.
    # Functions absent from call_trace are intentionally ignored.
    mock_returns: dict[str, str] = {}
    for inp in inputs:
        if inp.get("type") == "mock_return":
            func_name = inp["function"]
            if func_name in call_counts:   # ← KEY FILTER: call_trace is authoritative
                mock_returns[func_name] = _format_value_for_cpp(inp.get("return_value", 0))
        elif inp.get("type") == "mock_struct_return":
            func_name = inp["function"]
            if func_name in call_counts:   # ← same filter for struct mocks
                mock_returns[func_name] = f"/* struct .{inp['member']} = {inp.get('value', 0)} */"

    # Step 2c: the set of functions to emit expectations for is exactly
    # the call_trace set — nothing more, nothing less.
    all_mock_funcs = set(call_counts.keys())

    for mfunc in sorted(all_mock_funcs):
        count  = call_counts.get(mfunc, 1)
        retval = mock_returns.get(mfunc)

        if retval and retval.startswith("/*"):
            # struct mock: emit comment + basic expectOneCall
            mock_lines.append(f"    {retval}")
            if count > 1:
                mock_lines.append(
                    f'    mock().expectNCalls({count}, "{mfunc}");'
                )
            else:
                mock_lines.append(
                    f'    mock().expectOneCall("{mfunc}");'
                )
        elif retval is not None:
            if count > 1:
                mock_lines.append(
                    f'    mock().expectNCalls({count}, "{mfunc}")'
                    f'.andReturnValue({retval});'
                )
            else:
                mock_lines.append(
                    f'    mock().expectOneCall("{mfunc}")'
                    f'.andReturnValue({retval});'
                )
        else:
            if count > 1:
                mock_lines.append(
                    f'    mock().expectNCalls({count}, "{mfunc}");'
                )
            else:
                mock_lines.append(
                    f'    mock().expectOneCall("{mfunc}");'
                )

    # -------------------------------------------------------------------
    # 3. Call the function under test
    # -------------------------------------------------------------------
    clean_return = _strip_static_qualifiers(func["return"])
    has_return = "void" not in clean_return
    if has_return:
        call_lines.append(f"    {clean_return} return_value = {call_expr};")
    else:
        call_lines.append(f"    {call_expr};")

    # -------------------------------------------------------------------
    # 4. CHECK_EQUAL assertions from outputs
    # -------------------------------------------------------------------
    for out in outputs:
        out_type  = out.get("type")
        expected  = _format_value_for_cpp(out.get("expected_value", out.get("value", 0)))

        if out_type == "return_value_check":
            if has_return:
                output_lines.append(f"    CHECK_EQUAL({expected}, return_value);")
        elif out_type == "global_variable_check":
            var_name = out.get("name", "/* unknown */")
            # TESSY reports sometimes mis-report the function name itself as a
            # global variable check; such a variable never exists, so skip it.
            if var_name == func.get("name"):
                continue
            output_lines.append(f"    CHECK_EQUAL({expected}, *{_pointer_name_for_json_variable(var_name)});")
        elif out_type == "function_argument":
            var_name = out.get("name", "/* unknown */")
            output_lines.append(
                f"    CHECK_EQUAL({expected}, *{_pointer_name_for_json_variable(var_name)});"
            )

    # -------------------------------------------------------------------
    # 5. mock().checkExpectations() — verifies all mocks were called
    # -------------------------------------------------------------------
    check_lines = ["    mock().checkExpectations();"] if all_mock_funcs else []

    # Join sections with exactly one blank line between any two non-empty
    # sections, so tests read as: inputs / mocks / call / asserts / verify.
    lines = []
    for section in (input_lines, mock_lines, call_lines, output_lines, check_lines):
        if not section:
            continue
        if lines:
            lines.append("")
        lines.extend(section)

    return lines


# -------------------------------------------------
# Step 3: Generate ONE test file per function
# -------------------------------------------------
def generate_test_file(
    module,
    func,
    pointers,
    tessy_data=None,
    static_func_names=None,
    force_direct_calls=False,
    json_argument_pointers=None,
):
    lines = []
    global first_file
    group_name = f"{func['name']}"
    args = func.get("args", [])
    call_args = ", ".join(arg["name"] for arg in args)
    _static_func_names = static_func_names or set()

    # For header-based generation, call functions directly and skip pointer indirection.
    if force_direct_calls:
        call_expr = f"{func['name']}({call_args})"
    else:
        # 🔥 SMART pointer handling
        # Static functions must be called via their function-pointer variable
        # (get_<name>_ptr), not directly — direct calls to file-scope statics
        # would be link errors in the unit-test build.
        if func["name"] in _static_func_names:
            call_expr = f"get_{func['name']}_ptr({call_args})"
        elif func["name"] in pointers:
            getter_name = pointers[func["name"]]["getter"]
            call_expr = f"{getter_name}()({call_args})"
        else:
            call_expr = f"{func['name']}({call_args})"

    # headers
    lines.append('/**')
    lines.append(f'* \\file test_{group_name}.cpp')
    lines.append(f'* \\brief Unit tests for {group_name}().')
    lines.append('* \\author Subhasish Singha <subhasish.singha1@kiongroup.com>')
    lines.append('*/')
    if first_file:
        lines.append('#include "CppUTest/CommandLineTestRunner.h"')
    lines.append('#include "CppUTest/TestHarness.h"')
    lines.append('#include "CppUTestExt/MockSupport.h"')
    lines.append("")
    lines.append('extern "C" {')
    lines.append(f'  #include "mock_{module}.h"')
    lines.append('}')
    lines.append("")

    # test group
    lines.append(f'TEST_GROUP({group_name})')
    lines.append("{")
    lines.append("    void setup()")
    lines.append("    {")
    lines.append("        mock().clear();")
    lines.append("    }")
    lines.append("    void teardown()")
    lines.append("    {")
    lines.append("        mock().clear();")
    lines.append("    }")
    lines.append("};")
    lines.append("")

    # ------------------------------------------------------------------
    # Determine test cases to emit:
    #   - If TESSY JSON was loaded, emit one TEST block per JSON test case.
    #   - Otherwise emit one skeleton TEST block (original behaviour).
    # ------------------------------------------------------------------
    testcases = tessy_data.get("testcases", []) if tessy_data else []

    if testcases:
        # ---- JSON-driven test cases ----
        for tc in testcases:
            tc_id   = tc.get("testcase_id", "TC_01")
            # CppUTest test name: no spaces, use tc_id directly
            test_name = f"{func['name']}_{tc_id}"

            lines.extend(_doxygen_test_comment(tc, func["name"], test_name).splitlines())
            lines.append(f'TEST({group_name}, {test_name})')
            lines.append("{")

            body = generate_test_body_from_json(tc, func, call_expr)
            lines.extend(body)

            lines.append("}")
            lines.append("")

    else:
        # ---- Skeleton fallback (original behaviour) ----
        test_name = f"{func['name']}_TestCase_1"
        skeleton_tc = {
            "inputs": [
                {
                    "type": "function_argument",
                    "name": arg["name"],
                    "value": arg.get("default", "0"),
                }
                for arg in args
            ],
            "outputs": [],
            "call_trace": [],
            "description": "",
        }

        lines.extend(_doxygen_test_comment(skeleton_tc, func["name"], test_name).splitlines())
        lines.append(f'TEST({group_name}, {test_name})')
        lines.append("{")

        for arg in args:
            if _is_function_pointer_list_type(arg["type"]):
                lines.extend(_render_function_pointer_list_declaration(arg, arg.get("default", "NULL")))
            elif arg.get("array"):
                lines.append(
                    f"    {arg['type']} {arg['name']}{arg['array']} = {arg['default']};"
                )
            else:
                lines.append(
                    f"    {arg['type']} {arg['name']} = {arg['default']};"
                )

        if args:
            lines.append("")

        _clean_ret = _strip_static_qualifiers(func["return"])
        if "void" not in _clean_ret:
            lines.append(f"    {_clean_ret} ret = {call_expr};")
            lines.append("    // TODO: add CHECKs")
        else:
            lines.append(f"    {call_expr};")
            lines.append("    // TODO: verify behavior")

        lines.append("}")
        lines.append("")

    if first_file:
        lines.append('CPPUTEST_DEFAULT_MAIN')
        first_file = False
    return "\n".join(lines)


# -------------------------------------------------
# Step 4: Generate Excel test plan
# -------------------------------------------------
# def generate_excel(module, functions):
#     rows = []

#     for i, f in enumerate(functions, start=1):
#         rows.append({
#             "TC_ID": f"TC_{module.upper()}_{i:03}",
#             "Function": f["name"],
#             "Description": f"Auto test for {f['name']}",
#             "Inputs": "",
#             "Expected": ""
#         })

#     df = pd.DataFrame(rows)
#     out_path = os.path.join(OUTPUT_DIR, f"{module}_testplan.xlsx")
#     df.to_excel(out_path, index=False)
#     print(f"Excel generated: {out_path}")


def extract_static_functions(code):
    """
    Detect static (including static inline) functions.
    These need UNIT_TESTING accessors.
    """

    pattern = re.compile(
    r'''
    ^\s*
    (?:
        static\s+inline\s+ |
        STATIC_INLINE\s+   |
        STATIC_IN_APP\s+   |
        static\s+
    )
    ([A-Za-z_][\w\s\*\(\)]*?)   # return type
    \s+
    ([A-Za-z_]\w+)              # function name
    \s*
    \(([^)]*)\)
    \s*
    \{
    ''',
    re.MULTILINE | re.VERBOSE
)

    static_funcs = []

    for ret, name, params in pattern.findall(code):
        static_funcs.append({
            "return": ret.strip(),
            "name": name.strip(),
            "params": params.strip()
        })

    return static_funcs
def generate_mock_files(output_dir, static_funcs, dependency_decls, type_aliases=None, json_argument_pointers=None):
    """Generate mock_<module>.h and mock_<module>.c with declarations and stubs."""
    directory_name = os.path.basename(os.path.normpath(output_dir))
    if not directory_name:
        directory_name = "module"

    file_stub = f"mock_{directory_name}"
    include_guard = f"MOCK_{directory_name.upper()}_H"

    header_lines = []
    header_lines.append('/**')
    header_lines.append(f'* \\file mock_{directory_name}.h')
    header_lines.append(f'* \\brief Mocks and stubs for {directory_name}.')
    header_lines.append('* \\author Subhasish Singha <subhasish.singha1@kiongroup.com>')
    header_lines.append('*/')
    header_lines.append("")
    header_lines.append(f"#ifndef {include_guard}")
    header_lines.append(f"#define {include_guard}")
    header_lines.append("")
    header_lines.append('#include "../../../src/bsw/pal/types.h"')
    header_lines.append('#include "../../../src/share/types_common.h"')
    header_lines.append('#include "../../../src/app/app_diag/dtc/dtc_lst_safety1.h"')
    header_lines.append('#include "../../../src/bsw/cfg/dtc_cfg.h"')
    header_lines.append("")
    header_lines.append("")
    header_lines.append('typedef enum sih_flag_e')
    header_lines.append('{')
    header_lines.append('   SIH_SAFETY1_DIS_RELEASE_TOG = 0 ,') 
    header_lines.append('   SIH_TRAC_BKSTOP             ,   ')
    header_lines.append('   SIH_TRAC_BRKJAM             ,   ')
    header_lines.append('   SIH_TRAC_ECOMBLUEQ          ,   ')
    header_lines.append('   SIH_TRAC_BYDRIV             ,   ')
    header_lines.append('   SIH_TRAC_BYSTOP             ,   ')
    header_lines.append('   SIH_TRAC_CEDE               ,   ')
    header_lines.append('   SIH_TRAC_CRSW               ,   ')
    header_lines.append('   SIH_TRAC_CUSTDEF            ,   ')
    header_lines.append('   SIH_TRAC_DEBFINV            ,   ')
    header_lines.append('   SIH_TRAC_DEPRSWITCH         ,   ')
    header_lines.append('   SIH_TRAC_FLY                ,   ')
    header_lines.append('   SIH_TRAC_FREEW              ,   ')
    header_lines.append('   SIH_TRAC_IPCTRLOFF          ,   ')
    header_lines.append('   SIH_TRAC_RIDE               ,   ')
    header_lines.append('   SIH_TRAC_SOFTSTOP           ,   ')
    header_lines.append('   SIH_TRAC_SPINDO             ,   ')
    header_lines.append('   SIH_TRAC_SPINDORE           ,   ')
    header_lines.append('   SIH_TRAC_SPFULM             ,   ')
    header_lines.append('   SIH_TRAC_SPLM18RE           ,   ')
    header_lines.append('   SIH_TRAC_SPLM18NR           ,   ')
    header_lines.append('   SIH_TRAC_SPLM30             ,   ')
    header_lines.append('   SIH_TRAC_SPLM40             ,   ')
    header_lines.append('   SIH_TRAC_SPLM45             ,   ')
    header_lines.append('   SIH_TRAC_SPLM60             ,   ')
    header_lines.append('   SIH_TRAC_SPLMLIION          ,   ')
    header_lines.append('   SIH_TRAC_SPLMSPPR           ,   ')
    header_lines.append('   SIH_TRAC_SPMALI1            ,   ')
    header_lines.append('   SIH_TRAC_SPMALI2            ,   ')
    header_lines.append('   SIH_TRAC_SPMALICUTOUT1      ,   ')
    header_lines.append('   SIH_TRAC_SPMALICUTOUT2      ,   ')
    header_lines.append('   SIH_TRAC_SPPRSWITCH         ,   ')
    header_lines.append('   SIH_TRAC_SPSOFTLA           ,   ')
    header_lines.append('   SIH_TRAC_SPLM_CO1           ,   ')
    header_lines.append('   SIH_TRAC_SPLM_CO2           ,   ')
    header_lines.append('   SIH_TRAC_SPLMAULILO         ,   ')
    header_lines.append('   SIH_TRAC_DUMMY2             ,   ')
    header_lines.append('   SIH_TRAC_SRWS               ,   ')
    header_lines.append('   SIH_TRAC_SRWSAGW            ,   ')
    header_lines.append('   SIH_TRAC_TIRE               ,   ')
    header_lines.append('   SIH_TRAC_TIREBY             ,   ')
    header_lines.append('   SIH_TRAC_TRACTPOWRED_LIB    ,   ')
    header_lines.append('   SIH_TRAC_TRCMDRE            ,   ')
    header_lines.append('   SIH_TRAC_TURTLE             ,   ')
    header_lines.append('   SIH_TRAC_WALK               ,   ')
    header_lines.append('   SIH_TRAC_WALKUF             ,   ')
    header_lines.append('   SIH_HYDR_BLUEQ              ,   ')
    header_lines.append('   SIH_HYDR_CUSTRABB           ,   ')
    header_lines.append('   SIH_HYDR_ISENUP             ,   ')
    header_lines.append('   SIH_HYDR_LISLOW             ,   ')
    header_lines.append('   SIH_HYDR_LISTOPHARD         ,   ')
    header_lines.append('   SIH_HYDR_LISTOPSOFT         ,   ')
    header_lines.append('   SIH_HYDR_LMPUMPOC           ,   ')
    header_lines.append('   SIH_HYDR_LOSTOP             ,   ')
    header_lines.append('   SIH_HYDR_MALIBOON           ,   ')
    header_lines.append('   SIH_HYDR_MALOSOFTLA         ,   ')
    header_lines.append('   SIH_HYDR_PRMALIHI           ,   ')
    header_lines.append('   SIH_HYDR_NOINLIMAIN         ,   ')
    header_lines.append('   SIH_HYDR_NOINLIREAR         ,   ')
    header_lines.append('   SIH_HYDR_NOINLOMAIN         ,   ')
    header_lines.append('   SIH_HYDR_NOINLOREAR         ,   ')
    header_lines.append('   SIH_HYDR_NOMALIEMU2         ,   ')
    header_lines.append('   SIH_HYDR_NOMALIMAIN         ,   ')
    header_lines.append('   SIH_HYDR_NOMALIMLS          ,   ')
    header_lines.append('   SIH_HYDR_NOMALIREAR         ,   ')
    header_lines.append('   SIH_HYDR_NOMALOEMU2         ,   ')
    header_lines.append('   SIH_HYDR_NOMALOMAIN         ,   ')
    header_lines.append('   SIH_HYDR_NOMALOMLS          ,   ')
    header_lines.append('   SIH_HYDR_NOMALOREAR         ,   ')
    header_lines.append('   SIH_HYDR_PALISTOP           ,   ')
    header_lines.append('   SIH_HYDR_PALOSTOP           ,   ')
    header_lines.append('   SIH_HYDR_POWSAVE2           ,   ')
    header_lines.append('   SIH_HYDR_PWM_LIMIT          ,   ')
    header_lines.append('   SIH_HYDR_SOFTSTOP           ,   ')
    header_lines.append('   SIH_HYDR_TURTLE             ,   ')
    header_lines.append('   SIH_HYDR_WAYSSTOP           ,   ')
    header_lines.append('   SIH_ACTU_ALLOFF             ,   ')
    header_lines.append('   SIH_ACTU_CASTWOFF           ,   ')
    header_lines.append('   SIH_ACTU_NOTUSED_1          ,   ')
    header_lines.append('   SIH_ACTU_HORNIOFF           ,   ')
    header_lines.append('   SIH_ACTU_NOTUSED_2          ,   ')
    header_lines.append('   SIH_ACTU_KCURELOFF          ,   ')
    header_lines.append('   SIH_ACTU_MCONTOFF           ,   ')
    header_lines.append('   SIH_ACTU_POWRPOFF           ,   ')
    header_lines.append('   SIH_ACTU_RELAYOFF           ,   ')
    header_lines.append('   SIH_ACTU_USENSOFF           ,   ')
    header_lines.append('   SIH_ACTU_US13VOFF           ,   ')
    header_lines.append('   SIH_HYDR_NOMALIINCH         ,   ')
    header_lines.append('   SIH_HYDR_NOMALOINCH         ,   ')
    header_lines.append('   SIH_HYDR_NOMALIINCHREAR     ,   ')
    header_lines.append('   SIH_HYDR_NOMALOINCHREAR     ,   ')
    header_lines.append('   SIH_HYDR_MALISOFTSTOP       ,   ')
    header_lines.append('   SIH_HYDR_MALOSOFTSTOP       ,   ')
    header_lines.append('   SIH_HYDR_AUTOLISTOP         ,   ')
    header_lines.append('   SIH_HYDR_AUTOLOSTOP         ,   ')
    header_lines.append('   SIH_HYDR_INLISOFTSTOP       ,   ')
    header_lines.append('   SIH_HYDR_INLOSOFTSTOP       ,   ')
    header_lines.append('   SIH_HYDR_STANDSTACK         ,   ')
    header_lines.append('   SIH_HYDR_INDOMAHINR         ,   ')
    header_lines.append('   SIH_TRAC_SPSMDDC            ,   ')
    header_lines.append('   SIH_ACTU_ADDOUTSOFF         ,   ')
    header_lines.append('   SIH_HYDR_PRINLIHI           ,   ')
    header_lines.append('   SIH_TRAC_ACPRSWITCH         ,   ')
    header_lines.append('   SIH_TRAC_SMOOTHPERF         ,   ')
    header_lines.append('   SIH_HYDR_KCULIMITLI         ,   ')
    header_lines.append('   SIH_HYDR_KCULIMITLO         ,   ')
    header_lines.append('   SIH_TRAC_ANTIVIBRA          ,   ')
    header_lines.append('   SIH_TRAC_SPCORED1           ,   ')
    header_lines.append('   SIH_TRAC_SPCORED2           ,   ')
    header_lines.append('   SIH_TRAC_SPDOUBST           ,   ')
    header_lines.append('   SIH_TRAC_AULOGRESMOD        ,   ')
    header_lines.append('   SIH_HYDR_AULOGRESMOD        ,   ')
    header_lines.append('   SIH_TRAC_WHSGSPRED          ,   ')
    header_lines.append('   SIH_TRAC_WHSGSPREDWR        ,   ')
    header_lines.append('   SIH_TRAC_SOFTSTOPFO         ,   ')
    header_lines.append('   SIH_TRAC_SOFTSTOPBA         ,   ')
    header_lines.append('   SIH_TRAC_SOFTSTOPBO         ,   ')
    header_lines.append('   SIH_TRAC_LODETSPRED         ,   ')
    header_lines.append('   SIH_TRAC_LODETSPREDWR        ,   ')
    header_lines.append('   SIH_TRAC_SPMALICUTOUT1WR    ,   ')
    header_lines.append('   SIH_TRAC_SPMALICUTOUT2WR    ,   ')
    header_lines.append('   SIH_TRAC_SPMALICUTOUT3         ,   ')
    header_lines.append('   SIH_TRAC_SPMALICUTOUT3WR        ,   ')
    header_lines.append('   SIH_CNT                     ,   ')
    header_lines.append('} sih_flag_t;')
    header_lines.append("")

    json_argument_pointers = json_argument_pointers or []


    for func in static_funcs:
        typedef_name = f"{func['name']}_ptr"
        getter_name = f"get_{func['name']}_ptr"
        params = func["params"].strip()
        if not params or params in {"void", "VO"}:
            params = "void"

        header_lines.append(
            f"typedef {func['return']} (*{typedef_name})({params});"
        )
        header_lines.append(
            f"extern {typedef_name} {getter_name};"
        )
        header_lines.append("")

    if static_funcs:
        header_lines.append("#ifdef UNIT_TESTING")
        for func in static_funcs:
            typedef_name = f"{func['name']}_ptr"
            getter_name = f"get_{func['name']}_ptr"
            header_lines.append(
                f"{typedef_name} {getter_name} = {func['name']};"
            )
        header_lines.append("#endif")
        header_lines.append("")

    if json_argument_pointers:
        header_lines.append("#ifdef UNIT_TESTING")
        for ptr in json_argument_pointers:
            if ptr.get("type"):
                header_lines.append(f"extern {ptr['type']} *{ptr['name']} = &{ptr['source']};")
            else:
                pass
                # header_lines.append(f"/* *{ptr['name']} ({ptr['source']}) */")
        header_lines.append("#endif")
        header_lines.append("")

    source_bodies = []
    for decl in dependency_decls:
        header_decl, source_body = render_dependency_stub(decl, type_aliases)
        header_lines.append(header_decl)
        source_bodies.append(source_body)

    if dependency_decls:
        header_lines.append("")

    header_lines.append(f"#endif /* {include_guard} */")

    header_path = os.path.join(output_dir, f"{file_stub}.h")
    with open(header_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header_lines))

    source_lines = [
        f"#include \"{file_stub}.h\"",
        "#include \"CppUTestExt/MockSupport_c.h\"",
        ""
    ]
    if source_bodies:
        source_lines.append("\n\n".join(source_bodies))
        source_lines.append("")

    source_path = os.path.join(output_dir, f"{file_stub}.c")
    with open(source_path, "w", encoding="utf-8") as f:
        f.write("\n".join(source_lines))

    print(f"Mock header generated: {header_path}")
    print(f"Mock source generated: {source_path}")

def parse_sisigpool_headers(header_files):
    """
    Scan headers for function pointer typedefs + extern instances.
    Returns list of dicts.
    """
    ptr_types = {}
    externs = []

    for hdr in header_files:
        try:
            with open(hdr, "r", errors="ignore") as f:
                text = f.read()
        except Exception:
            continue

        # find typedefs
        for m in FUNC_PTR_TYPEDEF_RE.finditer(text):
            ptr_types[m.group("type")] = {
                "ret": m.group("ret"),
                "args": m.group("args"),
            }

        # find externs
        for m in EXTERN_PTR_RE.finditer(text):
            externs.append({
                "type": m.group("type"),
                "name": m.group("name"),
            })

    # keep only matching typedef-backed externs
    results = []
    for ex in externs:
        if ex["type"] in ptr_types:
            results.append({
                "typedef": ex["type"],
                "name": ex["name"],
                "ret": ptr_types[ex["type"]]["ret"],
                "args": ptr_types[ex["type"]]["args"],
            })

    return results

# -------------------------------------------------
# Step 5: Generate Makefile for CppUTest
# -------------------------------------------------
def generate_makefile(output_dir, source_file_abs_path, project_root):
    """
    Generate a Makefile for CppUTest in the output directory.
    
    Args:
        output_dir: path to output directory (relative or absolute)
        source_file_abs_path: absolute path to source .c file
        project_root: absolute path to project root
    """
    # Convert to absolute paths for calculation
    output_dir_abs = os.path.abspath(output_dir)
    
    module_name = os.path.basename(source_file_abs_path).replace(".c", "").replace(".h", "")
    
    # Get the directory containing the source file
    source_dir = os.path.dirname(source_file_abs_path)
    source_dir_rel = os.path.relpath(source_dir, output_dir_abs)
    
    # Normalize path separators to forward slashes for consistency
    source_dir_rel = source_dir_rel.replace("\\", "/")
    
    # Generate Makefile content in clang/common.mk format.
    makefile_lines = [
        "# ==========================================================",
        f"# {module_name} Unit Test",
        "# ==========================================================",
        "",
        f"MODULE_NAME := {module_name}",
        f"SRC_DIR     := {source_dir_rel}",
        "",
        "INCLUDE_DIRS := \\",
        "    . \\",
        "    $(SRC_DIR) \\",
        "    ../../../src/app \\",
        "    ../../../src",
        "",
        "EXTRA_CFLAGS += -DWH_EE_TC3 -DKWPC06 -DD2_SAMPLE",
        "EXTRA_CXXFLAGS += -DWH_EE_TC3 -DKWPC06 -DD2_SAMPLE",
        "",
        f"PROD_SRC := $(SRC_DIR)/{module_name}.c \\",
        f"            ./mock_{module_name}.c",
        "",
        f"ALL_PROD_C := $(SRC_DIR)/{module_name}.c",
        "",
        "include ../../test_automation/common.mk",
    ]
    
    makefile_path = os.path.join(output_dir, "Makefile")
    with open(makefile_path, "w", encoding="utf-8") as f:
        f.write("\n".join(makefile_lines))
    
    print(f"Makefile generated: {makefile_path}")

# -------------------------------------------------
# Step 6: Generate build_test.bat
# -------------------------------------------------
def generate_build_test_bat(output_dir, json_dir=None):
    """
    Generate a build_test.bat file for building tests on Windows.
    """
    bat_lines = [
        "@echo off",
        "setlocal",
        "",
        "set MSYS_ROOT=C:\\msys64",
        "set MSYSTEM=MINGW32",
        "set CHERE_INVOKING=1",
        "",
        "echo.",
        "echo ===============================================",
        "echo Running Coverage Build in mingw32...",
        "echo ===============================================",
        "echo.",
        "",
        "REM Get script directory",
        "set SCRIPT_DIR=%~dp0",
        "",
        "REM Remove trailing backslash",
        "if \"%SCRIPT_DIR:~-1%\"==\"\\\" set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%",
        "",
        "echo Project Path: %SCRIPT_DIR%",
        "echo.",
        "",
        "\"%MSYS_ROOT%\\usr\\bin\\bash.exe\" --login -c \"cd \\\"%SCRIPT_DIR%\\\" && make all\"",
        "",
        "echo.   ",
        "echo ===============================================",
        "echo Done.",
        "echo JSON: coverage.json",
        "echo ===============================================",
        "pause",
    ]
    
    bat_path = os.path.join(output_dir, "build_test.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write("\n".join(bat_lines))
    
    print(f"Build script generated: {bat_path}")

    if json_dir:
        delete_extracted_json_files(json_dir)



def delete_extracted_json_files(json_dir):
    if not json_dir:
        return
    if not os.path.isdir(json_dir):
        print(f"JSON cleanup skipped: directory not found: {json_dir}")
        return

    deleted_count = 0
    for filename in os.listdir(json_dir):
        if filename.lower().endswith(".json"):
            file_path = os.path.join(json_dir, filename)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except OSError as exc:
                    print(f"WARNING: Failed to delete {file_path}: {exc}")

    print(f"JSON cleanup complete: deleted {deleted_count} file(s) from {json_dir}")


def _safe_extract_zip(zip_file, dest_dir):
    """
    Extract *zip_file* into *dest_dir*, rejecting any member whose resolved
    path would escape *dest_dir* (zip-slip protection).
    """
    dest_root = os.path.abspath(dest_dir)
    for member in zip_file.namelist():
        member_path = os.path.abspath(os.path.join(dest_root, member))
        if member_path != dest_root and not member_path.startswith(dest_root + os.sep):
            raise ValueError(f"Unsafe path in zip archive: {member}")
    zip_file.extractall(dest_dir)


def _resolve_zip_source(pdf_path):
    """
    Resolve a PDF source path that may point *inside* a .zip archive, e.g.:

        C:\\...\\konl_busw.zip\\konl_busw\\TestDetails

    If a ".zip" component is present, the archive is extracted to a temporary
    directory and the equivalent path inside the extracted tree is returned.

    Returns a tuple ``(resolved_path, temp_dir)`` where:
      - ``resolved_path`` is a real filesystem path to scan for PDFs, or None
        when the archive / inner path is invalid.
      - ``temp_dir`` is the temporary directory to delete afterwards, or None
        when no extraction was required.
    """
    raw = str(pdf_path)
    parts = [p for p in re.split(r"[\\/]+", raw) if p != ""]

    zip_index = next(
        (i for i, part in enumerate(parts) if part.lower().endswith(".zip")),
        None,
    )

    # No archive in the path: use it as-is.
    if zip_index is None:
        return raw, None

    zip_path = os.sep.join(parts[: zip_index + 1])
    inner_parts = parts[zip_index + 1:]

    if not os.path.isfile(zip_path):
        print(f"WARNING: Zip archive not found: {zip_path}")
        return None, None

    temp_dir = tempfile.mkdtemp(prefix="tessy_pdf_")
    try:
        with zipfile.ZipFile(zip_path) as zip_file:
            _safe_extract_zip(zip_file, temp_dir)
    except (zipfile.BadZipFile, ValueError) as exc:
        print(f"WARNING: Could not extract zip archive '{zip_path}': {exc}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None

    resolved = os.path.join(temp_dir, *inner_parts) if inner_parts else temp_dir
    if not os.path.exists(resolved):
        print(f"WARNING: Path inside zip not found: {os.sep.join(inner_parts)} "
              f"(archive: {os.path.basename(zip_path)})")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None

    print(f"Extracted zip archive '{os.path.basename(zip_path)}' for PDF access.")
    return resolved, temp_dir


def extract_pdf_to_json(pdf_path, json_output_dir):
    """
    Run the TESSY PDF extraction engine on *pdf_path* (a single PDF file, a
    directory of PDFs, or a path inside a .zip archive) and write one JSON file
    per function into *json_output_dir*.

    Returns the output directory if at least one test case report was
    extracted, otherwise None (so the caller can fall back to skeleton
    generation).
    """
    extraction_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "Extraction"
    )
    if not os.path.isdir(extraction_dir):
        print(f"WARNING: Extraction engine not found at: {extraction_dir}")
        return None

    if extraction_dir not in sys.path:
        sys.path.insert(0, extraction_dir)

    try:
        extraction_main = importlib.import_module("main")
    except Exception as exc:
        print(f"WARNING: Could not load PDF extraction engine: {exc}")
        return None

    # Resolve a path that may point inside a .zip archive. When extraction to a
    # temp directory is required, temp_dir is cleaned up once run() completes.
    resolved_pdf_path, temp_dir = _resolve_zip_source(pdf_path)
    if resolved_pdf_path is None:
        return None

    # Start from a clean output directory so stale JSON from a previous run
    # does not leak into this generation.
    delete_extracted_json_files(json_output_dir)
    os.makedirs(json_output_dir, exist_ok=True)

    print(f"Extracting test case data from PDF source: {resolved_pdf_path}")
    try:
        reports = extraction_main.run(
            input_path=resolved_pdf_path,
            output_dir=json_output_dir,
        )
    except Exception as exc:
        print(f"WARNING: PDF extraction failed: {exc}")
        return None
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if not reports:
        print(f"No test case data extracted from: {pdf_path}")
        return None

    print(f"PDF extraction complete: {len(reports)} function report(s) written "
          f"to {json_output_dir}")
    return json_output_dir
# -------------------------------------------------
# MAIN
# -------------------------------------------------
def main():
    global OUTPUT_DIR
    parser = argparse.ArgumentParser(
        description="Generate unit test skeletons and mock files from a C source file."
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="Source file name or path (e.g. spv_app.c, spv_app.h or src/app/spv_app.c)."
    )
    parser.add_argument(
        "--json-dir",
        default=None,
        help=(
            "Directory containing TESSY-extracted JSON files "
            "(one file per function, named <function_name>.json). "
            "When provided, generated test files will contain real test cases "
            "populated from the JSON instead of TODO skeletons."
        )
    )
    parser.add_argument(
        "--pdf-dir",
        default=None,
        help=(
            "Path to a TESSY PDF file or a directory of PDFs. When provided, "
            "the tool first extracts test case data from the PDF(s) into JSON "
            "and then generates fully populated test cases in a single run. "
            "If no PDF data is available, it falls back to skeleton generation."
        )
    )
    args = parser.parse_args()

    project_root = get_project_root()

    if args.source:
        input_c_file = find_source_file(args.source, project_root)
    else:
        input_c_file = find_c_file()

    if not input_c_file:
        if args.source:
            print(f"ERROR: Could not find source file '{args.source}' in project: {project_root}")
        else:
            print("ERROR: No .c file found inside input/ folder")
            print("TIP: You can also run with a source argument, e.g.:")
            print("  python generator.py spv_app.c")
        return

    print(f"Using source file: {input_c_file}")
    is_header_input = input_c_file.lower().endswith(".h")
    if is_header_input:
        print("Header input detected: static function pointer generation will be skipped.")

    # Validate json_dir if supplied
    json_dir = args.json_dir

    # If a PDF source is supplied, extract its data first and use the resulting
    # JSON directory. This enables a single command to both extract and
    # generate. When no PDF data is available, fall back to skeleton generation.
    if args.pdf_dir:
        extraction_output = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "Extraction",
            "extracted_json_files",
        )
        extracted_dir = extract_pdf_to_json(args.pdf_dir, extraction_output)
        if extracted_dir:
            json_dir = extracted_dir
        else:
            print("No extracted test data available; proceeding with skeleton "
                  "generation.")

    if json_dir:
        if not os.path.isdir(json_dir):
            print(f"WARNING: --json-dir '{json_dir}' does not exist or is not a directory. "
                  f"Falling back to skeleton generation.")
            json_dir = None
        else:
            print(f"TESSY JSON directory: {json_dir}")

    with open(input_c_file, "r", encoding="latin-1") as f:
        code = f.read()

    var_type_map = _build_var_type_map(code)

    type_header_paths = [
        os.path.join(INC_DIR, "types.h")
    ]
    type_aliases = load_type_aliases(type_header_paths)

    module = os.path.basename(input_c_file).replace(".c", "").replace(".h", "")
    OUTPUT_DIR = module
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Using output directory: {OUTPUT_DIR}")

    # -------------------------------------------------
    # 🔥 Generate Makefile (only if source file was found)
    # -------------------------------------------------
    generate_makefile(OUTPUT_DIR, input_c_file, project_root)

    # -------------------------------------------------
    # normal function parsing
    # -------------------------------------------------
    functions = extract_functions(code, type_aliases)
    externals = extract_external_calls(code)
    pointers = extract_test_pointers(code)

    # Detect static functions for C source inputs only.
    # For header inputs, treat as no-static mode and force direct calls.
    if is_header_input:
        static_funcs = []
        static_func_names = set()
    else:
        static_funcs = extract_static_functions(code)
        static_func_names = {f["name"] for f in static_funcs}

    print("Detected functions:", len(functions))
    print("Detected externals:", externals)
    print("Detected test pointers:", pointers)
    print("Detected static functions:", sorted(static_func_names))

    header_files = glob.glob(
        os.path.join(project_root, "**", "*.h"),
        recursive=True
    )
    declaration_map = extract_function_declarations_from_headers(header_files)
    dependency_decls, missing_decls = resolve_dependency_declarations(
        code,
        functions,
        static_funcs,
        declaration_map,
    )
    print("Resolved dependency declarations:", len(dependency_decls))
    if missing_decls:
        print("Unresolved dependency declarations:", missing_decls)
        macro_stubs = infer_macro_function_stubs(code, missing_decls)
        dependency_decls.extend(macro_stubs)

    # -------------------------------------------------
    # generate test files
    # All test skeleton files are written first so mock headers
    # and build files exist before the JSON pass overwrites bodies.
    # Then, for each function that has a matching JSON, re-write
    # the file with fully populated test cases.
    # -------------------------------------------------
    global first_file
    json_argument_pointers = []
    json_argument_pointer_names = set()
    for func in functions:
        # Load TESSY JSON for this function (None if not found)
        tessy_data = load_tessy_json(json_dir, func["name"])
        for ptr in collect_json_function_argument_pointers(tessy_data, func, var_type_map):
            if ptr["name"] not in json_argument_pointer_names:
                json_argument_pointers.append(ptr)
                json_argument_pointer_names.add(ptr["name"])

        test_code = generate_test_file(
            module, func, pointers,
            tessy_data=tessy_data,
            static_func_names=static_func_names,
            force_direct_calls=is_header_input,
            json_argument_pointers=json_argument_pointers,
        )
        test_path = os.path.join(
            OUTPUT_DIR,
            f"test_{func['name']}.cpp"
        )

        with open(test_path, "w", encoding="utf-8") as f:
            f.write(test_code)

        first_file = False
        if tessy_data:
            tc_count = len(tessy_data.get("testcases", []))
            print(f"Test file generated (JSON, {tc_count} TC): {test_path}")
        else:
            print(f"Test file generated (skeleton):            {test_path}")

    # -------------------------------------------------
    # excel
    # -------------------------------------------------
    # generate_excel(module, functions)

    # -------------------------------------------------
    # Generate mock header/source with static pointers + dependency stubs
    # -------------------------------------------------
    generate_mock_files(
        OUTPUT_DIR,
        static_funcs,
        dependency_decls,
        type_aliases=type_aliases,
        json_argument_pointers=json_argument_pointers,
    )

    

    # -------------------------------------------------
    # 🔥 Generate build script
    # -------------------------------------------------
    generate_build_test_bat(OUTPUT_DIR, json_dir=json_dir)

if __name__ == "__main__":
    main()