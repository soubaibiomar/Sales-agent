import sys, json
sys.path.insert(0, ".")
from src.backend.main import app
from fastapi.routing import APIRoute, APIWebSocketRoute
def deps(d, acc):
    for sub in d.dependencies:
        acc.add(getattr(sub.call, "__name__", str(sub.call)))
        deps(sub, acc)
    return acc
def walk(routes, prefix=""):
    for r in routes:
        tn=type(r).__name__
        if isinstance(r,(APIRoute,APIWebSocketRoute)):
            yield prefix, r
        elif tn=="_IncludedRouter":
            sub = getattr(r,"router",None) or getattr(r,"original_router",None)
            p = getattr(r,"prefix","") or ""
            if sub is None:
                print("ATTRS", [a for a in dir(r) if not a.startswith("__")], file=sys.stderr); continue
            yield from walk(sub.routes, prefix+p)
rows=[]
for pre,r in walk(app.routes):
    names = deps(r.dependant,set())
    authed = any(n in names for n in ("get_security_context","permission_checker","require_privileged_mfa"))
    rows.append({"path":pre+r.path,"methods":sorted(getattr(r,"methods",None) or ["WS"]),"auth":authed,"deps":sorted(names)})
print(json.dumps(rows,indent=1))
