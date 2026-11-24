"""
Escapes data interpolated into HTML template literals in src/frontend/js/pages/*.js
(inspection finding F-20: API values were concatenated into innerHTML unescaped).

A small JavaScript lexer finds template literals (with nesting). Inside a template whose
static text contains HTML markup ("<"), every `${expr}` is wrapped as
`${SalesViews.esc(expr)}` unless the expression itself produces markup or another
template (contains a backtick, "<", ".map(" or ".join("), or is already escaped.
Idempotent. Prints a per-file count.

Usage: python scripts/frontend_escape_templates.py
"""
import glob
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "frontend", "js", "pages"))
SKIP = ("handlers.js", "login.js")


def find_matching_brace(src: str, i: int) -> int:
    """src[i] is just after '${'; returns index of the matching '}' (handles strings/templates)."""
    depth = 1
    while i < len(src):
        c = src[i]
        if c in "'\"":
            i = skip_string(src, i)
            continue
        if c == "`":
            i = skip_template(src, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced ${")


def skip_string(src: str, i: int) -> int:
    q = src[i]
    i += 1
    while i < len(src) and src[i] != q:
        i += 2 if src[i] == "\\" else 1
    return i + 1


def skip_template(src: str, i: int) -> int:
    i += 1
    while i < len(src) and src[i] != "`":
        if src[i] == "\\":
            i += 2
            continue
        if src.startswith("${", i):
            i = find_matching_brace(src, i + 2) + 1
            continue
        i += 1
    return i + 1


def transform_template(tpl: str) -> tuple:
    """tpl includes the backticks. Returns (new_tpl, wrapped_count)."""
    out, i, wrapped = ["`"], 1, 0
    static_text = re.sub(r"\$\{", "", tpl)
    is_html = "<" in static_text.replace("${", "")
    while i < len(tpl) - 1:
        if tpl[i] == "\\":
            out.append(tpl[i:i + 2]); i += 2; continue
        if tpl.startswith("${", i):
            end = find_matching_brace(tpl, i + 2)
            expr = tpl[i + 2:end]
            # recurse into nested templates inside the expression
            expr = transform_source(expr)[0]
            e = expr.strip()
            simple = not any(tok in e for tok in ("`", "<", ".map(", ".join(", "SalesViews.esc(", "esc("))
            if is_html and simple and e:
                out.append("${SalesViews.esc(" + e + ")}"); wrapped += 1
            else:
                out.append("${" + expr + "}")
            i = end + 1
            continue
        out.append(tpl[i]); i += 1
    out.append("`")
    return "".join(out), wrapped


def transform_source(src: str) -> tuple:
    out, i, total = [], 0, 0
    while i < len(src):
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i); j = len(src) if j == -1 else j
            out.append(src[i:j]); i = j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2); j = len(src) if j == -1 else j + 2
            out.append(src[i:j]); i = j; continue
        if c in "'\"":
            j = skip_string(src, i); out.append(src[i:j]); i = j; continue
        if c == "`":
            j = skip_template(src, i)
            new, n = transform_template(src[i:j])
            out.append(new); total += n; i = j; continue
        out.append(c); i += 1
    return "".join(out), total


if __name__ == "__main__":
    for path in sorted(glob.glob(os.path.join(ROOT, "*.js"))):
        if path.endswith(SKIP):
            continue
        src = open(path, encoding="utf-8").read()
        new, n = transform_source(src)
        if n:
            open(path, "w", encoding="utf-8").write(new)
        print(f"{os.path.basename(path)}: {n} interpolations escaped")
