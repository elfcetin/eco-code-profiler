"""Eski ve yeni kodu yalıtılmış bir alt süreçte çalıştırıp karşılaştırır ve ölçer.

Kullanıcı kodu ASLA bu süreçte çalıştırılmaz. Her doğrulama:
- geçici bir dizinde, `sys.executable -I` (yalıtılmış mod) ile ayrı bir süreçte,
- sadeleştirilmiş ortam değişkenleriyle (API anahtarları vb. aktarılmaz),
- zaman aşımıyla (varsayılan 60 sn; aşılırsa tüm süreç grubu öldürülür),
- POSIX'te `resource` ile bellek/CPU/dosya boyutu sınırlarıyla
çalıştırılır. Not: ağ erişimi bu katmanda engellenmez (kapalı ağ varsayımı).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_TIMEOUT = 60
DEFAULT_MEMORY_MB = 1024

# Alt süreçte çalışan betik. Yalnızca standart kütüphane kullanır.
RUNNER = r'''
import copy
import inspect
import json
import os
import random
import sys
import timeit
import types

PAYLOAD_PATH, RESULT_PATH = sys.argv[1], sys.argv[2]
with open(PAYLOAD_PATH, encoding="utf-8") as fh:
    P = json.load(fh)


def limit_resources(memory_mb, cpu_seconds):
    try:
        import resource
    except ImportError:  # Windows
        return
    limit = memory_mb * 1024 * 1024
    targets = [("RLIMIT_AS", limit), ("RLIMIT_DATA", limit),
               ("RLIMIT_CPU", cpu_seconds), ("RLIMIT_FSIZE", 50 * 1024 * 1024)]
    for name, value in targets:
        res = getattr(resource, name, None)
        if res is None:
            continue
        try:
            soft, hard = resource.getrlimit(res)
            if hard != resource.RLIM_INFINITY:
                value = min(value, hard)
            resource.setrlimit(res, (value, hard))
        except (ValueError, OSError):
            pass


RESULT = {"phase": "start", "load_error": None, "cases": [], "benchmark": []}


def save():
    tmp = RESULT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh, ensure_ascii=False)
    os.replace(tmp, RESULT_PATH)


def short(value, limit=500):
    try:
        text = repr(value)
    except Exception as exc:
        text = f"<repr hatası: {type(exc).__name__}>"
    return text if len(text) <= limit else text[:limit] + "…"


def load(name, source):
    module = types.ModuleType(name)
    module.__file__ = name + ".py"
    sys.modules[name] = module
    exec(compile(source, name + ".py", "exec"), module.__dict__)
    return module


def call(fn, args):
    try:
        value = fn(*args)
        if isinstance(value, types.GeneratorType) or (
            hasattr(value, "__next__") and hasattr(value, "__iter__")
        ):
            value = list(value)
        return {"ok": True, "value": value}
    except (Exception, SystemExit) as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def values_equal(a, b):
    try:
        return type(a) is type(b) and bool(a == b)
    except Exception:
        return False


def outcomes_equal(a, b):
    if a["ok"] != b["ok"]:
        return False
    if not a["ok"]:
        return a["error"] == b["error"]  # aynı tip hata -> eşit
    return values_equal(a["value"], b["value"])


def describe(outcome):
    if outcome["ok"]:
        return short(outcome["value"])
    return f"{outcome['error']}: {outcome['message']}"[:500]


def fit_args(fn, args):
    """Benchmark ifadesi tek argümanı açık liste olarak verdiyse sarmala."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return args
    try:
        sig.bind(*args)
        return args
    except TypeError:
        try:
            sig.bind(args)
            return [args]
        except TypeError:
            return args


def binds(fn, args):
    """Argümanlar fonksiyon imzasına uyuyor mu?"""
    try:
        inspect.signature(fn).bind(*args)
        return True
    except TypeError:
        return False
    except ValueError:  # imzası okunamayan (yerleşik) çağrılabilirler
        return True


def get_fn(module, name):
    obj = module
    for part in name.split("."):
        obj = getattr(obj, part, None)
    return obj if callable(obj) else None


limit_resources(P["memory_mb"], P["timeout"] + 5)

# --- 1) yükleme --------------------------------------------------------------
modules = {}
for label, key in (("orijinal", "original_code"), ("yeşil", "green_code")):
    try:
        modules[label] = load("eco_" + ("original" if label == "orijinal" else "green"), P[key])
    except BaseException as exc:
        RESULT["load_error"] = f"{label} kod yüklenemedi: {type(exc).__name__}: {exc}"
        RESULT["phase"] = "done"
        save()
        sys.exit(0)
old_mod, new_mod = modules["orijinal"], modules["yeşil"]
RESULT["phase"] = "cases"
save()

# --- 2) doğruluk karşılaştırması --------------------------------------------
def derived_variants(args):
    """LLM'den bağımsız ek girdiler: liste argümanları azalan sıralı ve ters çevrilmiş.

    LLM'in seçtiği küçük/sıralı girdilerde tesadüfen doğru çıkan sıra hatalarını yakalar
    (ör. küçük tamsayılı set'ler artan sırada dolaşılır).
    """
    seen = [args]
    variants = []
    for label, transform in (("azalan sıralı", lambda a: sorted(a, reverse=True)), ("ters", lambda a: a[::-1])):
        try:
            candidate = [transform(a) if isinstance(a, list) and len(a) > 1 else a for a in args]
        except TypeError:  # karşılaştırılamayan elemanlar
            continue
        if candidate not in seen:
            seen.append(candidate)
            variants.append((label, candidate))
    return variants


def fuzz_args(args, rng, size):
    """Örnek girdideki liste argümanlarını aynı türde, bol tekrarlı rastgele listelerle değiştirir."""
    out, changed = [], False
    for a in args:
        if isinstance(a, list) and a and all(type(x) is int for x in a):
            lo, hi = min(a), max(a)
            span = max(hi - lo, 10)
            out.append([rng.randint(lo - span, hi + span) for _ in range(size)])
            changed = True
        elif isinstance(a, list) and a and all(type(x) in (int, float, str) for x in a):
            out.append([rng.choice(a) for _ in range(size)])
            changed = True
        else:
            out.append(a)
    return out if changed else None


def list_size(args):
    return max((len(a) for a in args if isinstance(a, list)), default=0)


BASES = {}  # fonksiyon -> rastgele girdi üretiminde örnek alınan geçerli girdi
SHRUNK = set()  # en küçük karşı örneği bulunmuş fonksiyonlar


def still_differs(old_fn, new_fn, args):
    if not binds(old_fn, args):
        return None
    old_out = call(old_fn, copy.deepcopy(args))
    new_out = call(new_fn, copy.deepcopy(args))
    if old_out["ok"] and not outcomes_equal(old_out, new_out):
        return old_out, new_out
    return None


def rank_normalize(a):
    """Tamsayıları sıra ve eşitlik ilişkisini koruyarak 1, 2, 3... değerlerine indirir."""
    if not (isinstance(a, list) and a and all(type(x) is int for x in a)):
        return a
    ranks = {v: i + 1 for i, v in enumerate(sorted(set(a)))}
    return [ranks[x] for x in a]


def shrink(old_fn, new_fn, args, budget=400):
    """Farkı koruyarak liste argümanlarından eleman siler (açgözlü küçültme).

    Küçük modellere 40 elemanlı bir karşı örnek yerine [1, 2, 2, 1] gibi okunabilir bir
    örnek göstermek, ikinci denemede hatanın anlaşılmasını kolaylaştırır.
    """
    best = list(args)
    changed = True
    while changed and budget > 0:
        changed = False
        for idx in range(len(best)):
            if not isinstance(best[idx], list):
                continue
            i = 0
            while i < len(best[idx]) and budget > 0:
                candidate = list(best)
                candidate[idx] = best[idx][:i] + best[idx][i + 1:]
                budget -= 1
                if still_differs(old_fn, new_fn, candidate):
                    best, changed = candidate, True
                else:
                    i += 1
    normalized = [rank_normalize(a) for a in best]
    if normalized != best and still_differs(old_fn, new_fn, normalized):
        best = normalized
    outcome = still_differs(old_fn, new_fn, best)
    if outcome is None or best == list(args):
        return None
    return {"input": short(best), "old": describe(outcome[0]), "new": describe(outcome[1])}


def run_case(name, old_fn, new_fn, args, derived=None):
    case = {"function": name, "input": short(args)}
    if derived:
        case["derived"] = derived
    if old_fn is None or new_fn is None:
        missing = "orijinal" if old_fn is None else "yeşil"
        case.update(old=None, new=None, equal=False, note=f"{name} {missing} kodda bulunamadı")
    elif not binds(old_fn, args):
        case.update(old=None, new=None, equal=False, invalid=True,
                    note="Geçersiz test girdisi: argümanlar fonksiyon imzasına uymuyor.")
    else:
        old_args, new_args = copy.deepcopy(args), copy.deepcopy(args)
        old_out, new_out = call(old_fn, old_args), call(new_fn, new_args)
        equal = outcomes_equal(old_out, new_out)
        case.update(old=describe(old_out), new=describe(new_out), equal=equal, old_ok=old_out["ok"])
        if equal and not values_equal(old_args, new_args):
            case["equal"] = False
            case["note"] = "Fonksiyonlar argümanları farklı biçimde değiştiriyor (yan etki farkı)."
        elif not equal and old_out["ok"] and name not in SHRUNK:
            minimal = shrink(old_fn, new_fn, args)
            if minimal:
                case["minimal"] = minimal
                SHRUNK.add(name)
    RESULT["cases"].append(case)
    save()
    return case


for name, inputs in P["test_inputs"].items():
    old_fn, new_fn = get_fn(old_mod, name), get_fn(new_mod, name)
    for args in inputs:
        if not isinstance(args, list):
            args = [args]
        case = run_case(name, old_fn, new_fn, args)
        if case.get("invalid") or old_fn is None or new_fn is None:
            continue
        for label, variant in derived_variants(args):
            run_case(name, old_fn, new_fn, variant, derived=label)
        if case.get("old_ok") and list_size(args) > list_size(BASES.get(name, [])):
            BASES[name] = args
    # LLM'in seçtiği girdilerden bağımsız, bol tekrarlı rastgele girdiler.
    if name in BASES:
        for k in range(3):
            variant = fuzz_args(BASES[name], random.Random(1000 + k), 40)
            if variant is not None:
                run_case(name, old_fn, new_fn, variant, derived="rastgele")
RESULT["phase"] = "benchmark"
save()

# --- 3) performans ölçümü ----------------------------------------------------
# LLM benchmark ifadesi vermediyse örnek girdiden 2000 elemanlı otomatik girdi üret.
benchmarks = dict(P["benchmark_input"])
for name in BASES:
    benchmarks.setdefault(name, None)

for name, expr in benchmarks.items():
    entry = {"function": name, "old_seconds": None, "new_seconds": None, "outputs_equal": None,
             "error": None, "auto": expr is None}
    RESULT["benchmark"].append(entry)
    old_fn, new_fn = get_fn(old_mod, name), get_fn(new_mod, name)
    if old_fn is None or new_fn is None:
        entry["error"] = f"{name} kodda bulunamadı"
        save()
        continue
    try:
        if expr is None:
            args = fuzz_args(BASES[name], random.Random(12345), 2000)
            if args is None:
                RESULT["benchmark"].pop()
                continue
        else:
            random.seed(12345)
            args = eval(expr, {"random": random, "__builtins__": __builtins__})
            args = list(args) if isinstance(args, (list, tuple)) else [args]
            args = fit_args(old_fn, args)
    except Exception as exc:
        entry["error"] = f"Benchmark girdisi üretilemedi: {type(exc).__name__}: {exc}"
        save()
        continue
    if not binds(old_fn, args):
        entry["error"] = "Benchmark girdisi fonksiyon imzasına uymuyor."
        save()
        continue

    outcomes = {}
    for label, fn in (("old", old_fn), ("new", new_fn)):
        copies = iter([copy.deepcopy(args) for _ in range(3)])
        holder = {}

        def stmt(fn=fn, copies=copies, holder=holder):
            holder["out"] = call(fn, next(copies))

        times = timeit.repeat(stmt, repeat=3, number=1)
        entry[label + "_seconds"] = min(times)
        outcomes[label] = holder["out"]
        save()
    entry["outputs_equal"] = outcomes_equal(outcomes["old"], outcomes["new"])
    if not outcomes["old"]["ok"] or not outcomes["new"]["ok"]:
        entry["error"] = "Benchmark çağrısı hata verdi: eski=" + describe(outcomes["old"]) + \
                         " / yeni=" + describe(outcomes["new"])
    save()

RESULT["phase"] = "done"
save()
'''


def _child_env() -> dict[str, str]:
    """Alt sürece yalnızca gerekli ortam değişkenlerini aktar (gizli anahtarlar sızmasın)."""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"}
    for key in ("SYSTEMROOT", "TEMP", "TMP"):  # Windows'ta Python'un çalışması için gerekli
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _run_child(workdir: Path, payload: dict, timeout: float) -> tuple[dict | None, bool, str]:
    runner = workdir / "runner.py"
    payload_path = workdir / "payload.json"
    result_path = workdir / "result.json"
    runner.write_text(RUNNER, encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    posix = os.name == "posix"
    proc = subprocess.Popen(
        [sys.executable, "-I", str(runner), str(payload_path), str(result_path)],
        cwd=workdir,
        env=_child_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=posix,
    )
    timed_out = False
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if posix:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()
        _, stderr = proc.communicate()

    result = None
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result = None
    return result, timed_out, (stderr or b"").decode("utf-8", "replace")[-2000:]


def _summarize_benchmark(entries: list[dict]) -> dict | None:
    if not entries:
        return None
    # Yalnızca iki sürümün de hatasız çalışıp aynı sonucu verdiği ölçümler toplama girer.
    measured = [
        e for e in entries
        if e["old_seconds"] is not None and e["new_seconds"] is not None
        and e["error"] is None and e["outputs_equal"] is True
    ]
    old = sum(e["old_seconds"] for e in measured) if measured else None
    new = sum(e["new_seconds"] for e in measured) if measured else None
    speedup = old / new if measured and new else None
    return {"old_seconds": old, "new_seconds": new, "speedup": speedup, "functions": entries}


def verify(
    original_code: str,
    green_code: str,
    test_inputs: dict[str, list],
    benchmark_input: dict[str, str] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    memory_mb: int = DEFAULT_MEMORY_MB,
) -> dict:
    """Eski ve yeni kodu karşılaştırır.

    Dönüş:
        {
          "passed": bool,
          "cases": [{"function", "input", "old", "new", "equal", "old_ok",
                     ["derived"], ["invalid"], ["note"],
                     ["minimal": {"input", "old", "new"}]}, ...],
          "benchmark": None | {"old_seconds", "new_seconds", "speedup",
                               "functions": [{"function", "old_seconds", "new_seconds",
                                              "outputs_equal", "error"}, ...]},
          "timed_out": bool,
          "error": None | str,
        }
    """
    payload = {
        "original_code": original_code,
        "green_code": green_code,
        "test_inputs": test_inputs or {},
        "benchmark_input": benchmark_input or {},
        "timeout": timeout,
        "memory_mb": memory_mb,
    }
    with tempfile.TemporaryDirectory(prefix="eco_verify_") as tmp:
        raw, timed_out, stderr = _run_child(Path(tmp), payload, timeout)

    raw = raw or {}
    phase = raw.get("phase")
    cases = raw.get("cases", [])
    benchmark = _summarize_benchmark(raw.get("benchmark", []))
    error = raw.get("load_error")

    if timed_out:
        if phase in ("benchmark", "done"):
            error = f"Performans ölçümü {timeout:g} saniyelik zaman aşımına takıldı."
            if benchmark is not None:
                benchmark["error"] = "zaman aşımı"
        else:
            error = (
                f"Zaman aşımı ({timeout:g} sn): kod test girdileriyle çalışırken bitmedi "
                "(sonsuz döngü veya aşırı yavaş kod olabilir)."
            )
    elif phase != "done" and error is None:
        error = "Doğrulama süreci beklenmedik biçimde sonlandı (bellek sınırı aşılmış olabilir)."
        if stderr.strip():
            error += f"\n{stderr.strip()}"

    if not cases and error is None:
        error = "Karşılaştırılacak test girdisi yok."

    cases_ok = phase in ("benchmark", "done") and bool(cases) and all(c["equal"] for c in cases)
    invalid = [c for c in cases if c.get("invalid")]
    if invalid and error is None:
        error = f"{len(invalid)} test girdisi fonksiyon imzasına uymuyor (geçersiz test)."
    # Tüm girdilerde iki sürüm de aynı hatayı veriyorsa hiçbir davranış test edilmemiştir.
    if cases_ok and not any(c.get("old_ok") for c in cases):
        cases_ok = False
        error = error or "Hiçbir test girdisi orijinal kodda hatasız çalışmadı; eşdeğerlik testi anlamlı değil."
    bench_ok = benchmark is None or all(
        e["outputs_equal"] is not False for e in benchmark["functions"]
    )
    if cases_ok and not bench_ok and error is None:
        error = "Benchmark girdisinde eski ve yeni kod farklı sonuç verdi."

    # Benchmark aşamasındaki zaman aşımı/çökme doğruluğu etkilemez; yalnızca ölçüm eksik kalır.
    return {
        "passed": cases_ok and bench_ok,
        "cases": cases,
        "benchmark": benchmark,
        "timed_out": timed_out,
        "error": error,
    }
