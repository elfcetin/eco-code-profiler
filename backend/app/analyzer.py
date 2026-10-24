"""AST tabanlı statik enerji israfı analizi.

LLM kullanmaz; yalnızca Python'un `ast` modülüyle çalışır. `analyze(code)`
fonksiyonu sözdizimi hatasını, üst seviye fonksiyonların tahmini zaman
karmaşıklığını ve "Yeşil Kod" desen ihlallerini (YK-01 … YK-10) döndürür.

Tespit kuralları koddadır; desenlerin başlık, etki ve aktif/pasif bilgisi ise
`catalog` parametresiyle veritabanından verilir (bkz. db.load_catalog).
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from typing import Iterable, Iterator

from .patterns import GREEN_PATTERNS

# pattern_code -> {title, impact, is_active}. Katalog verilmezse (ör. birim testleri) ya da
# veritabanında bir desen kaydı yoksa patterns.py'deki başlangıç değerleri kullanılır.
DEFAULT_CATALOG: dict[str, dict] = {
    p["code"]: {"title": p["title"], "impact": p["impact"], "is_active": True} for p in GREEN_PATTERNS
}

LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)
COMP_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
ANY_LOOP = LOOP_NODES + COMP_NODES
FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPE_BOUNDARY = FUNC_NODES + (ast.Lambda, ast.ClassDef)

CACHE_DECORATORS = {"lru_cache", "cache"}
AGGREGATORS = {"sum", "any", "all", "min", "max"}
# Argümanının tamamını dolaşan yerleşik fonksiyonlar (tek argümanla çağrılınca).
IMPLICIT_ITERATION = AGGREGATORS | {"sorted"}
LIST_PRODUCERS = {"list", "sorted"}
NON_LIST_PRODUCERS = {"set", "frozenset", "dict", "Counter", "defaultdict", "OrderedDict"}
LIST_FILLERS = {"append", "extend", "insert"}
MUTATING_METHODS = {
    "append", "extend", "insert", "pop", "remove", "clear", "add", "update",
    "discard", "popitem", "setdefault", "sort", "reverse",
}
# Argüman olarak verilen değişkeni değiştirmediği bilinen yerleşikler.
PURE_BUILTINS = {
    "len", "str", "repr", "print", "int", "float", "bool", "abs", "round", "hash",
    "id", "type", "isinstance", "format", "range", "enumerate", "zip", "list",
    "tuple", "set", "frozenset", "dict", "sorted", "reversed",
} | AGGREGATORS

SUPERSCRIPTS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


@dataclass
class Finding:
    line: int
    pattern_code: str
    title: str
    detail: str
    impact: str


@dataclass
class _Scope:
    list_vars: set[str]
    str_vars: set[str]


@dataclass
class _LoopFrame:
    node: ast.AST
    modified: set[str]


# --------------------------------------------------------------------------- #
# Genel yardımcılar
# --------------------------------------------------------------------------- #

def _walk_local(root: ast.AST | Iterable[ast.AST]) -> Iterator[ast.AST]:
    """ast.walk gibi; ama iç fonksiyon/lambda/sınıf gövdelerine inmez."""
    stack = [root] if isinstance(root, ast.AST) else list(root)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, SCOPE_BOUNDARY):
                stack.append(child)


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in _walk_local(node) if isinstance(n, ast.Name)}


def _base_name(node: ast.AST) -> str | None:
    """`a.b[0].c` -> "a"."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_int_zero(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) is int and node.value == 0


def _comp_elements(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.DictComp):
        return [node.key, node.value]
    return [node.elt]


def _loop_parts(node: ast.AST) -> tuple[list[ast.AST], list[ast.AST]]:
    """(bir kez çalışan kısımlar, her iterasyonda çalışan kısımlar)."""
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return [node.iter, *node.orelse], [node.target, *node.body]
    if isinstance(node, ast.While):
        return list(node.orelse), [node.test, *node.body]
    gens = node.generators
    inside: list[ast.AST] = _comp_elements(node)
    for k, gen in enumerate(gens):
        inside.append(gen.target)
        inside.extend(gen.ifs)
        if k:
            inside.append(gen.iter)
    return [gens[0].iter], inside


def _loop_units(node: ast.AST) -> list[set[str]]:
    """Döngünün her seviyesi için döngü değişkeni adları."""
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return [_names(node.target)]
    if isinstance(node, ast.While):
        return [set()]
    return [_names(gen.target) for gen in node.generators]


def _modified_names(parts: list[ast.AST]) -> set[str]:
    """Döngü içinde yeniden atanan veya değiştirilmiş olabilecek adlar."""
    names: set[str] = set()
    for node in _walk_local(parts):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if base := _base_name(node.value):
                names.add(base)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in MUTATING_METHODS:
                if base := _base_name(func.value):
                    names.add(base)
            # Bilinmeyen bir fonksiyona verilen değişken orada değiştirilmiş olabilir.
            if not (isinstance(func, ast.Name) and func.id in PURE_BUILTINS):
                for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                    if isinstance(arg, ast.Name):
                        names.add(arg.id)
    return names


def _target_value_pairs(target: ast.AST, value: ast.AST | None) -> list[tuple[str, ast.AST | None]]:
    if isinstance(target, ast.Name):
        return [(target.id, value)]
    if isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
            return [p for t, v in zip(target.elts, value.elts) for p in _target_value_pairs(t, v)]
        return [(name, None) for name in _names(target)]
    return []


def _build_scope(node: ast.AST, parent: _Scope | None) -> _Scope:
    """Bir modül/fonksiyon/sınıf kapsamındaki liste ve string değişkenlerini bulur."""
    params: set[str] = set()
    if isinstance(node, FUNC_NODES):
        a = node.args
        params = {arg.arg for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs]}
        params |= {arg.arg for arg in (a.vararg, a.kwarg) if arg}

    bound = set(params)
    list_assigned: set[str] = set()
    filled: set[str] = set()
    non_list: set[str] = set()
    str_assigned: set[str] = set()

    for n in _walk_local(node.body):
        pairs: list[tuple[str, ast.AST | None]] = []
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            bound.add(n.id)
        elif isinstance(n, ast.Assign):
            pairs = [p for t in n.targets for p in _target_value_pairs(t, n.value)]
        elif isinstance(n, (ast.AnnAssign, ast.NamedExpr)) and n.value is not None:
            pairs = _target_value_pairs(n.target, n.value)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in LIST_FILLERS and isinstance(n.func.value, ast.Name):
                filled.add(n.func.value.id)

        for name, value in pairs:
            if isinstance(value, (ast.List, ast.ListComp)):
                list_assigned.add(name)
            elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                if value.func.id in LIST_PRODUCERS:
                    list_assigned.add(name)
                elif value.func.id in NON_LIST_PRODUCERS:
                    non_list.add(name)
            elif isinstance(value, (ast.Set, ast.SetComp, ast.Dict, ast.DictComp)):
                non_list.add(name)
            elif isinstance(value, ast.JoinedStr) or (
                isinstance(value, ast.Constant) and isinstance(value.value, str)
            ):
                str_assigned.add(name)

    list_vars = (list_assigned | filled) - params - non_list
    if parent is not None:
        list_vars |= parent.list_vars - bound
    return _Scope(list_vars=list_vars, str_vars=str_assigned - params)


# --------------------------------------------------------------------------- #
# Karmaşıklık tahmini
# --------------------------------------------------------------------------- #

def _is_implicit_iteration(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id in IMPLICIT_ITERATION:
        return len(node.args) == 1
    return isinstance(func, ast.Attribute) and func.attr == "sort"


def _max_loop_depth(node: ast.AST, depth: int = 0) -> int:
    if isinstance(node, SCOPE_BOUNDARY):
        return depth
    if isinstance(node, LOOP_NODES):
        outside, inside = _loop_parts(node)
        return max(
            [depth + 1]
            + [_max_loop_depth(p, depth) for p in outside]
            + [_max_loop_depth(p, depth + 1) for p in inside]
        )
    if isinstance(node, COMP_NODES):
        gens = node.generators
        best = max(depth + len(gens), _max_loop_depth(gens[0].iter, depth))
        for k, gen in enumerate(gens):
            if k:
                best = max(best, _max_loop_depth(gen.iter, depth + k))
            for cond in gen.ifs:
                best = max(best, _max_loop_depth(cond, depth + k + 1))
        for elt in _comp_elements(node):
            best = max(best, _max_loop_depth(elt, depth + len(gens)))
        return best
    best = depth + 1 if _is_implicit_iteration(node) else depth
    for child in ast.iter_child_nodes(node):
        best = max(best, _max_loop_depth(child, depth))
    return best


def _complexity_label(order: int) -> str:
    if order <= 0:
        return "O(1)"
    if order == 1:
        return "O(N)"
    return "O(N" + str(order).translate(SUPERSCRIPTS) + ")"


def _is_cached(fn: ast.AST) -> bool:
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", None)
        if name in CACHE_DECORATORS:
            return True
    return False


def _has_manual_memo(fn: ast.AST) -> bool:
    """`if n in memo: return memo[n]` ... `memo[n] = ...` kalıbı."""
    checked: set[str] = set()
    stored: set[str] = set()
    for n in _walk_local(fn.body):
        if isinstance(n, ast.Compare):
            for op, comp in zip(n.ops, n.comparators):
                if isinstance(op, ast.In) and isinstance(comp, ast.Name):
                    checked.add(comp.id)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
            if isinstance(n.func.value, ast.Name):
                checked.add(n.func.value.id)
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store):
            if isinstance(n.value, ast.Name):
                stored.add(n.value.id)
    return bool(checked & stored)


def _recursive_call_count(fn: ast.AST) -> int:
    """Tek bir çağrı yolunda fonksiyonun kendini en fazla kaç kez çağırdığı.

    if/else dalları birbirini dışladığından toplanmaz, en büyüğü alınır
    (ör. özyinelemeli ikili arama 1 sayılır, fib(n-1) + fib(n-2) 2 sayılır).
    """
    name = fn.name

    def is_self_call(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == name
        return (
            isinstance(func, ast.Attribute)
            and func.attr == name
            and isinstance(func.value, ast.Name)
            and func.value.id in ("self", "cls")
        )

    def expr(node: ast.AST) -> int:
        if isinstance(node, SCOPE_BOUNDARY):
            return 0
        if isinstance(node, ast.IfExp):
            return expr(node.test) + max(expr(node.body), expr(node.orelse))
        own = 1 if is_self_call(node) else 0
        return own + sum(expr(child) for child in ast.iter_child_nodes(node))

    def terminates(stmts: list[ast.stmt]) -> bool:
        if not stmts:
            return False
        last = stmts[-1]
        if isinstance(last, (ast.Return, ast.Raise)):
            return True
        return isinstance(last, ast.If) and terminates(last.body) and terminates(last.orelse)

    def stmt(st: ast.stmt) -> int:
        if isinstance(st, (ast.With, ast.AsyncWith)):
            return sum(expr(item) for item in st.items) + block(st.body)
        if isinstance(st, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            handlers = max((block(h.body) for h in st.handlers), default=0)
            return block(st.body) + handlers + block(st.orelse) + block(st.finalbody)
        if isinstance(st, ast.Match):
            return expr(st.subject) + max((block(c.body) for c in st.cases), default=0)
        return expr(st)

    def block(stmts: list[ast.stmt]) -> int:
        total = 0
        for i, st in enumerate(stmts):
            if isinstance(st, ast.If):
                rest = block(stmts[i + 1:])
                body = block(st.body) + (0 if terminates(st.body) else rest)
                orelse = block(st.orelse) + (0 if terminates(st.orelse) else rest)
                return total + expr(st.test) + max(body, orelse)
            total += stmt(st)
            if isinstance(st, (ast.Return, ast.Raise)):
                return total
        return total

    return block(fn.body)


def _function_info(fn: ast.AST, qualname: str) -> dict:
    depth = max((_max_loop_depth(st) for st in fn.body), default=0)
    calls = _recursive_call_count(fn)
    memoized = _is_cached(fn) or _has_manual_memo(fn)

    if calls >= 2 and not memoized:
        complexity = "O(2^N)"
        reason = f"Fonksiyon kendini bir çağrıda {calls} kez çağırıyor (önbelleksiz özyineleme)."
    else:
        order = depth + (1 if calls else 0)
        complexity = _complexity_label(order)
        if calls:
            reason = f"Özyineleme ve en fazla {depth} seviye iç içe döngü."
        elif depth:
            reason = f"En derin döngü iç içeliği: {depth}."
        else:
            reason = "Döngü veya özyineleme yok."

    return {
        "name": qualname,
        "line": fn.lineno,
        "complexity": complexity,
        "loop_depth": depth,
        "recursive_calls": calls,
        "memoized": memoized,
        "reason": reason,
    }


def _collect_functions(tree: ast.Module) -> list[dict]:
    result = []
    for node in tree.body:
        if isinstance(node, FUNC_NODES):
            result.append(_function_info(node, node.name))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, FUNC_NODES):
                    result.append(_function_info(item, f"{node.name}.{item.name}"))
    return result


# --------------------------------------------------------------------------- #
# Desen tespiti
# --------------------------------------------------------------------------- #

class _FindingCollector:
    def __init__(self, catalog: dict[str, dict]) -> None:
        self.catalog = catalog
        self.findings: list[Finding] = []
        self._seen: set[tuple[int, str, str]] = set()

    def add(self, line: int, code: str, detail: str) -> None:
        key = (line, code, detail)
        if key in self._seen:
            return
        self._seen.add(key)
        info = self.catalog.get(code) or DEFAULT_CATALOG[code]
        if not info["is_active"]:
            return  # pasif desenler raporlanmaz
        self.findings.append(Finding(line, code, info["title"], detail, info["impact"]))

    # -- dolaşma ------------------------------------------------------------ #

    def visit(self, node: ast.AST, scope: _Scope, loops: tuple[_LoopFrame, ...]) -> None:
        if isinstance(node, FUNC_NODES):
            self._check_recursion(node)
            a = node.args
            for child in [*node.decorator_list, *a.defaults, *(d for d in a.kw_defaults if d)]:
                self.visit(child, scope, loops)
            inner = _build_scope(node, scope)
            for st in node.body:
                self.visit(st, inner, ())
            return
        if isinstance(node, ast.ClassDef):
            for child in [*node.decorator_list, *node.bases]:
                self.visit(child, scope, loops)
            inner = _build_scope(node, scope)
            for st in node.body:
                self.visit(st, inner, ())
            return
        if isinstance(node, ast.Lambda):
            self.visit(node.body, scope, ())
            return
        if isinstance(node, ANY_LOOP):
            self._visit_loop(node, scope, loops)
            return

        self._check_node(node, scope, loops)
        for child in ast.iter_child_nodes(node):
            self.visit(child, scope, loops)

    def _visit_loop(self, node: ast.AST, scope: _Scope, loops: tuple[_LoopFrame, ...]) -> None:
        outside, inside = _loop_parts(node)
        if not loops:
            self._check_nest(node, inside)
        for part in outside:
            self.visit(part, scope, loops)
        frame = _LoopFrame(node, _modified_names(inside))
        for part in inside:
            self.visit(part, scope, (*loops, frame))

    # -- YK-01 / YK-05 ------------------------------------------------------ #

    def _check_nest(self, outer: ast.AST, inside: list[ast.AST]) -> None:
        """En dıştaki döngü için iç içelik ve two-sum kontrolü (bir kez raporlanır)."""
        units = _loop_units(outer)
        for node in _walk_local(inside):
            if isinstance(node, ANY_LOOP):
                units.extend(_loop_units(node))
        if len(units) < 2:
            return

        for node in _walk_local(inside):
            if not isinstance(node, ast.Compare) or not any(isinstance(op, ast.Eq) for op in node.ops):
                continue
            operands = [node.left, *node.comparators]
            if not any(isinstance(o, ast.BinOp) and isinstance(o.op, (ast.Add, ast.Sub)) for o in operands):
                continue
            used = _names(node)
            if sum(1 for unit in units if unit & used) >= 2:
                self.add(
                    outer.lineno,
                    "YK-05",
                    f"{node.lineno}. satırdaki karşılaştırma, iki farklı döngünün elemanlarının "
                    "toplamını/farkını bir hedefle kıyaslıyor; bu O(N²) bir çift araması. "
                    "Görülen değerleri bir set/dict'te tutup her eleman için `hedef - x` "
                    "değerine O(1) sürede bakarak tek geçişte (O(N)) çözülebilir.",
                )
                return

        self.add(
            outer.lineno,
            "YK-01",
            f"Bu döngünün içinde {len(units) - 1} seviye daha döngü var; çalışma süresi "
            "girdi boyutuyla polinom (O(N²) veya daha kötü) artar. İç döngüdeki arama "
            "set/dict ile O(1)'e indirilebiliyor mu, ya da veri önceden gruplanıp/sıralanıp "
            "tek geçişte işlenebiliyor mu değerlendirin.",
        )

    # -- YK-06 -------------------------------------------------------------- #

    def _check_recursion(self, fn: ast.AST) -> None:
        calls = _recursive_call_count(fn)
        if calls < 2 or _is_cached(fn) or _has_manual_memo(fn):
            return
        self.add(
            fn.lineno,
            "YK-06",
            f"`{fn.name}` tek bir çağrıda kendini {calls} kez çağırıyor ve sonuçları "
            "önbelleğe almıyor; aynı alt problemler tekrar tekrar hesaplanır ve süre "
            "üstel (O(2^N)) büyüyebilir. `@functools.lru_cache` / `@functools.cache` "
            "ekleyin ya da yinelemeli (bottom-up) bir çözüme geçin.",
        )

    # -- tekil düğüm kontrolleri ---------------------------------------------- #

    def _check_node(self, node: ast.AST, scope: _Scope, loops: tuple[_LoopFrame, ...]) -> None:
        if isinstance(node, ast.Call):
            self._check_aggregator(node)
        if not loops:
            return
        frame = loops[-1]
        if isinstance(node, ast.Compare):
            self._check_membership(node, scope)
        elif isinstance(node, ast.AugAssign):
            self._check_str_concat(node, scope)
        elif isinstance(node, ast.Call):
            self._check_len(node, frame)
            self._check_list_front(node)
            self._check_sort(node)
            self._check_invariant_setup(node, frame)

    def _check_membership(self, node: ast.Compare, scope: _Scope) -> None:  # YK-02
        for op, comp in zip(node.ops, node.comparators):
            if isinstance(op, (ast.In, ast.NotIn)) and isinstance(comp, ast.Name) and comp.id in scope.list_vars:
                keyword = "in" if isinstance(op, ast.In) else "not in"
                self.add(
                    node.lineno,
                    "YK-02",
                    f"`{keyword} {comp.id}` listede doğrusal arama yapar (O(N)); döngü içinde "
                    "toplam maliyet O(N²)'ye çıkar. Üyelik kontrolü için `set` kullanın "
                    "(sıra gerekiyorsa listeyi ayrıca tutup kontrolü set üzerinden yapın).",
                )

    def _check_str_concat(self, node: ast.AugAssign, scope: _Scope) -> None:  # YK-03
        if isinstance(node.op, ast.Add) and isinstance(node.target, ast.Name) and node.target.id in scope.str_vars:
            name = node.target.id
            self.add(
                node.lineno,
                "YK-03",
                f"`{name}` string'ine döngüde `+=` ile ekleme yapılıyor. String'ler değişmez "
                "olduğundan bu genelde her adımda yeni bir kopya oluşturur. CPython, "
                "referansı tek olan string'lerde `+=` için yerinde genişletme optimizasyonu "
                "yaptığından pratikteki etki çoğu zaman küçüktür; ancak bu davranış garanti "
                "değildir (PyPy vb.). Parçaları listeye ekleyip sonda `''.join(...)` kullanın.",
            )

    def _check_len(self, node: ast.Call, frame: _LoopFrame) -> None:  # YK-04
        if not (isinstance(node.func, ast.Name) and node.func.id == "len"):
            return
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Name):
            return
        name = node.args[0].id
        if name in frame.modified:
            return
        self.add(
            node.lineno,
            "YK-04",
            f"`len({name})` döngünün her turunda yeniden çağrılıyor ama `{name}` döngü "
            f"içinde değişmiyor. Değeri döngüden önce bir değişkene alın "
            f"(ör. `n = len({name})`). len() O(1) olduğundan kazanç küçüktür.",
        )

    def _check_list_front(self, node: ast.Call) -> None:  # YK-07
        func = node.func
        if not isinstance(func, ast.Attribute) or not node.args:
            return
        if func.attr == "pop" and len(node.args) == 1 and _is_int_zero(node.args[0]):
            call = "pop(0)"
        elif func.attr == "insert" and _is_int_zero(node.args[0]):
            call = "insert(0, ...)"
        else:
            return
        self.add(
            node.lineno,
            "YK-07",
            f"`.{call}` listenin tüm elemanlarını kaydırır (O(N)); döngü içinde O(N²) olur. "
            "Kuyruk/çift uçlu yapı için `collections.deque` ve `popleft()`/`appendleft()` "
            "kullanın.",
        )

    def _check_sort(self, node: ast.Call) -> None:  # YK-08
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "sort":
            call = ".sort()"
        elif isinstance(func, ast.Name) and func.id == "sorted":
            call = "sorted()"
        else:
            return
        self.add(
            node.lineno,
            "YK-08",
            f"`{call}` döngünün her turunda çalışıyor (her biri O(N log N)). Sıralamayı "
            "döngüden önce bir kez yapın; sürekli sıralı yapı gerekiyorsa `heapq` veya "
            "`bisect.insort` kullanın.",
        )

    def _check_invariant_setup(self, node: ast.Call, frame: _LoopFrame) -> None:  # YK-10
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "compile" and isinstance(func.value, ast.Name) and func.value.id == "re":
            call = "re.compile()"
            advice = "Deseni döngüden önce bir kez derleyin."
        elif isinstance(func, ast.Name) and func.id == "open":
            call = "open()"
            advice = "Dosyayı döngüden önce bir kez açın ve döngüde aynı tanıtıcıyı kullanın."
        else:
            return
        used: set[str] = set()
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            used |= _names(arg)
        if used & frame.modified:
            return  # argümanlar her turda değişiyor (ör. farklı dosyalar), meşru kullanım.
        self.add(
            node.lineno,
            "YK-10",
            f"`{call}` döngü içinde aynı argümanlarla tekrar tekrar çağrılıyor; her çağrı "
            f"gereksiz derleme/sistem çağrısı (I/O) maliyeti doğurur. {advice}",
        )

    def _check_aggregator(self, node: ast.Call) -> None:  # YK-09
        func = node.func
        if isinstance(func, ast.Name) and func.id in AGGREGATORS and node.args and isinstance(node.args[0], ast.ListComp):
            self.add(
                node.lineno,
                "YK-09",
                f"`{func.id}([...])` önce tüm ara listeyi bellekte oluşturur. Köşeli "
                f"parantezleri kaldırıp generator ifadesi verin: `{func.id}(... for ...)`; "
                "bellek kullanımı O(1)'e iner"
                + (" ve any/all erken sonlanabilir." if func.id in ("any", "all") else "."),
            )


# --------------------------------------------------------------------------- #
# Genel API
# --------------------------------------------------------------------------- #

def analyze(code: str, catalog: dict[str, dict] | None = None) -> dict:
    """Kodu statik olarak analiz eder.

    catalog: kod -> {title, impact, is_active} (db.load_catalog). Pasif desenler
    bulgulara eklenmez. Verilmezse patterns.py'deki başlangıç değerleri kullanılır.

    Dönüş:
        {
          "syntax_error": None | {"message": str, "line": int | None, "offset": int | None},
          "functions": [{"name", "line", "complexity", "loop_depth",
                         "recursive_calls", "memoized", "reason"}, ...],
          "findings": [{"line", "pattern_code", "title", "detail", "impact"}, ...],
        }
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {
            "syntax_error": {"message": exc.msg, "line": exc.lineno, "offset": exc.offset},
            "functions": [],
            "findings": [],
        }
    except ValueError as exc:  # ör. kaynakta null byte
        return {
            "syntax_error": {"message": str(exc), "line": None, "offset": None},
            "functions": [],
            "findings": [],
        }

    collector = _FindingCollector(catalog or DEFAULT_CATALOG)
    module_scope = _build_scope(tree, None)
    for st in tree.body:
        collector.visit(st, module_scope, ())

    findings = sorted(collector.findings, key=lambda f: (f.line, f.pattern_code))
    return {
        "syntax_error": None,
        "functions": _collect_functions(tree),
        "findings": [asdict(f) for f in findings],
    }
