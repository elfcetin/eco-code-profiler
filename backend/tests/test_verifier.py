import os
import time

import pytest

from app.patterns import PATTERNS_BY_CODE
from app.verifier import verify

YK05 = PATTERNS_BY_CODE["YK-05"]
ORIGINAL = YK05["example_before"]
GREEN = YK05["example_after"]
TEST_INPUTS = {"find_pair": [[[], 3], [[1], 2], [[1, 2, 3, 4], 7], [[3, 3, 4], 6], [[5, 1, 5, 1], 6]]}
BENCH = {"find_pair": "[[random.randint(0, 10**9) for _ in range(2000)], -1]"}


def test_correct_optimization_passes_and_is_benchmarked():
    result = verify(ORIGINAL, GREEN, TEST_INPUTS, BENCH)

    assert result["error"] is None, result
    assert result["passed"] is True
    assert result["timed_out"] is False
    assert len([c for c in result["cases"] if "derived" not in c]) == 5
    assert all(c["equal"] for c in result["cases"])

    bench = result["benchmark"]
    assert bench["old_seconds"] > 0 and bench["new_seconds"] > 0
    assert bench["speedup"] > 1  # O(N²) -> O(N), 2000 elemanda belirgin
    assert bench["functions"][0]["outputs_equal"] is True


def test_broken_optimization_fails():
    # Hata: aynı değeri iki kez kullanabiliyor ([3, 4], 6 -> (0, 0) döndürür).
    broken = (
        "def find_pair(numbers, target):\n"
        "    seen = {x: i for i, x in enumerate(numbers)}\n"
        "    for i, x in enumerate(numbers):\n"
        "        if target - x in seen:\n"
        "            return (i, seen[target - x])\n"
        "    return None\n"
    )
    result = verify(ORIGINAL, broken, TEST_INPUTS)

    assert result["passed"] is False
    bad = [c for c in result["cases"] if not c["equal"]]
    assert bad and bad[0]["old"] != bad[0]["new"]


def test_infinite_loop_times_out():
    hanging = "def find_pair(numbers, target):\n    while True:\n        pass\n"
    start = time.monotonic()
    result = verify(ORIGINAL, hanging, TEST_INPUTS, timeout=3)

    assert time.monotonic() - start < 10
    assert result["timed_out"] is True
    assert result["passed"] is False
    assert "Zaman aşımı" in result["error"]


def test_same_exception_type_counts_as_equal():
    old = "def head(xs):\n    return xs[0]\n"
    new = "def head(xs):\n    for x in xs:\n        return x\n    raise IndexError('boş')\n"
    result = verify(old, new, {"head": [[[1, 2]], [[]]]})
    assert result["passed"] is True
    empty_case = next(c for c in result["cases"] if c["input"] == "[[]]")
    assert "IndexError" in empty_case["old"]


def test_different_exception_type_is_not_equal():
    old = "def head(xs):\n    return xs[0]\n"
    new = "def head(xs):\n    if not xs:\n        raise ValueError('boş')\n    return xs[0]\n"
    assert verify(old, new, {"head": [[[]]]})["passed"] is False


def test_output_order_matters():
    old = "def uniq(xs):\n    out = []\n    for x in xs:\n        if x not in out:\n            out.append(x)\n    return out\n"
    new = "def uniq(xs):\n    return sorted(set(xs))\n"
    assert verify(old, new, {"uniq": [[[3, 1, 3, 2]]]})["passed"] is False


def test_different_argument_mutation_is_not_equal():
    old = "def total(xs):\n    return sum(xs)\n"
    new = "def total(xs):\n    s = sum(xs)\n    xs.clear()\n    return s\n"
    result = verify(old, new, {"total": [[[1, 2, 3]]]})
    assert result["passed"] is False
    assert "yan etki" in result["cases"][0]["note"].lower()


def test_benchmark_single_list_argument_is_wrapped():
    old = "def total(xs):\n    t = 0\n    for x in xs:\n        t += x\n    return t\n"
    new = "def total(xs):\n    return sum(xs)\n"
    result = verify(old, new, {"total": [[[1, 2]]]}, {"total": "[random.random() for _ in range(5000)]"})
    entry = result["benchmark"]["functions"][0]
    assert entry["error"] is None and entry["old_seconds"] is not None


def test_code_runs_in_isolated_subprocess(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "gizli")
    code = (
        "import os\n"
        "open('marker.txt', 'w').write('x')\n"
        "def info():\n"
        "    return [os.environ.get('GEMINI_API_KEY'), os.getpid()]\n"
    )
    result = verify(code, code, {"info": [[]]})
    case = result["cases"][0]

    assert not (tmp_path / "marker.txt").exists()  # dosya geçici dizine yazıldı
    assert "gizli" not in case["old"]  # gizli ortam değişkeni aktarılmadı
    assert str(os.getpid()) not in case["old"]  # ayrı süreç


def test_load_error_is_reported():
    result = verify("def f(:\n    pass\n", "def f():\n    pass\n", {"f": [[]]})
    assert result["passed"] is False
    assert "orijinal kod yüklenemedi" in result["error"]


# --------------------------------------------------------------------------- #
# Gerçek kullanımda görülen hata: LLM tek argümanlı fonksiyona 2 argümanlı girdi
# verdi, iki sürüm de aynı TypeError'ı fırlattı ve test "geçti" sanıldı.
# --------------------------------------------------------------------------- #

FIND_DUPLICATES = (
    "def find_duplicates(items):\n"
    "    duplicates = []\n"
    "    for i in range(len(items)):\n"
    "        for j in range(i + 1, len(items)):\n"
    "            if items[i] == items[j] and items[i] not in duplicates:\n"
    "                duplicates.append(items[i])\n"
    "    return duplicates\n"
)
# LLM'in ürettiği hatalı kod (ekran görüntüsünden).
LLM_WRONG_GREEN = (
    "def find_duplicates(items):\n"
    "    seen = set()\n"
    "    duplicates = [x for x in items if (x in seen or seen.add(x))]\n"
    "    return [x for x in duplicates if duplicates.count(x) > 1]\n"
)
WRONG_ARITY_INPUTS = {"find_duplicates": [[[1, 2, 3, 4, 5], []], [[1, 2, 2, 3, 4], [2]], [[], []]]}


def test_inputs_not_matching_signature_are_invalid():
    result = verify(FIND_DUPLICATES, LLM_WRONG_GREEN, WRONG_ARITY_INPUTS)
    assert result["passed"] is False
    assert all(c.get("invalid") and not c["equal"] for c in result["cases"])
    assert "imzasına uymuyor" in result["error"]


def test_all_inputs_failing_in_original_is_not_meaningful():
    old = "def head(xs):\n    return xs[0]\n"
    new = "def head(xs):\n    return xs[0]\n"
    result = verify(old, new, {"head": [[[]], [[]]]})
    assert result["passed"] is False
    assert "anlamlı değil" in result["error"]


def test_llm_wrong_green_code_fails_with_valid_inputs():
    inputs = {"find_duplicates": [[[1, 2, 2, 3, 4]], [[]], [[3, 1, 3, 1]], [[5, 5, 5]]]}
    result = verify(FIND_DUPLICATES, LLM_WRONG_GREEN, inputs)
    assert result["passed"] is False
    assert any(not c["equal"] for c in result["cases"])


def test_benchmark_with_different_outputs_is_not_counted_as_speedup():
    old = "def f(xs):\n    return sorted(xs)\n"
    new = "def f(xs):\n    return list(xs)\n"
    result = verify(old, new, {"f": [[[1, 2]]]}, {"f": "[[random.random() for _ in range(1000)]]"})
    bench = result["benchmark"]
    assert bench["functions"][0]["outputs_equal"] is False
    assert bench["speedup"] is None and bench["old_seconds"] is None
    assert result["passed"] is False


def test_first_completed_pair_differs_when_several_pairs_exist():
    """Eski YK-05 örneği (ilk tamamlanan çift) çok çözümlü girdide farklı çift döndürüyordu."""
    first_completed = (
        "def find_pair(nums, target):\n"
        "    seen = {}\n"
        "    for j, x in enumerate(nums):\n"
        "        i = seen.get(target - x)\n"
        "        if i is not None:\n"
        "            return (i, j)\n"
        "        seen.setdefault(x, j)\n"
        "    return None\n"
    )
    result = verify(ORIGINAL, first_completed, {"find_pair": [[[1, 2, 3, 4, 5], 7]]})
    assert result["passed"] is False
    assert result["cases"][0]["old"] == "(1, 4)" and result["cases"][0]["new"] == "(2, 3)"


def test_order_preserving_two_sum_passes_on_multi_solution_inputs():
    inputs = {"find_pair": [[[1, 2, 3, 4, 5], 7], [[3, 3, 3], 6], [[5, 1, 5, 1], 6], [[0, 0], 1]]}
    assert verify(ORIGINAL, GREEN, inputs)["passed"] is True


# --------------------------------------------------------------------------- #
# Türetilmiş girdiler (qwen2.5-coder gerçekte list(set(...)) döndürdü ve LLM'in küçük,
# artan sıralı girdilerinde tesadüfen doğru çıktı)
# --------------------------------------------------------------------------- #

SET_ORDER_GREEN = (
    "def find_duplicates(items):\n"
    "    seen = set()\n"
    "    duplicates = set()\n"
    "    for item in items:\n"
    "        if item in seen:\n"
    "            duplicates.add(item)\n"
    "        else:\n"
    "            seen.add(item)\n"
    "    return list(duplicates)\n"
)


def test_derived_inputs_catch_coincidental_set_order():
    lucky_inputs = {"find_duplicates": [[[1, 2, 3, 2, 1]], [[]], [[1, 1]], [[1, 2, 2, 3, 3]]]}
    result = verify(FIND_DUPLICATES, SET_ORDER_GREEN, lucky_inputs)
    llm_cases = [c for c in result["cases"] if "derived" not in c]
    assert all(c["equal"] for c in llm_cases)  # LLM girdileri hatayı göstermiyor...
    assert result["passed"] is False  # ...türetilmiş girdiler gösteriyor
    assert any(c.get("derived") == "azalan sıralı" and not c["equal"] for c in result["cases"])


def test_derived_inputs_do_not_reject_correct_code():
    green = (
        "def find_duplicates(items):\n"
        "    counts = {}\n"
        "    for x in items:\n"
        "        counts[x] = counts.get(x, 0) + 1\n"
        "    seen = set()\n"
        "    out = []\n"
        "    for x in items:\n"
        "        if counts[x] > 1 and x not in seen:\n"
        "            seen.add(x)\n"
        "            out.append(x)\n"
        "    return out\n"
    )
    inputs = {"find_duplicates": [[[1, 2, 3, 2, 1]], [[]], [["b", "a", "b"]], [[5, 5, 4, 4]]]}
    result = verify(FIND_DUPLICATES, green, inputs)
    assert result["passed"] is True, result
    assert any(c.get("derived") for c in result["cases"])


def test_random_inputs_catch_set_order_even_with_weak_llm_inputs():
    """Gerçekte kaçan durum: LLM girdilerinde en fazla bir tekrar eden değer vardı, benchmark yoktu."""
    weak_inputs = {"find_duplicates": [[[3, 1, 3, 2]], [[]], [[7]], [[5, 5, 5]]]}
    result = verify(FIND_DUPLICATES, SET_ORDER_GREEN, weak_inputs)  # benchmark_input yok
    assert all(c["equal"] for c in result["cases"] if not c.get("derived"))
    assert any(c.get("derived") == "rastgele" and not c["equal"] for c in result["cases"])
    assert result["passed"] is False


def test_automatic_benchmark_when_llm_gives_none():
    result = verify(ORIGINAL, GREEN, TEST_INPUTS)  # benchmark_input yok
    entry = result["benchmark"]["functions"][0]
    assert entry["auto"] is True and entry["outputs_equal"] is True
    assert entry["old_seconds"] is not None and entry["new_seconds"] is not None
    assert result["passed"] is True


def test_failing_input_is_shrunk_to_minimal_counterexample():
    """qwen2.5-coder gerçekte 'ikinci görülme' sırasıyla döndüren kod yazdı."""
    second_occurrence = (
        "def find_duplicates(items):\n"
        "    seen, dups = {}, {}\n"
        "    for x in items:\n"
        "        if x in seen:\n"
        "            dups[x] = True\n"
        "        else:\n"
        "            seen[x] = True\n"
        "    return list(dups.keys())\n"
    )
    long_input = [[4, 12, -6, 3, 2, -7, 5, -4, 8, 4, -5, -2, 12, -2, 2, 12, 6, -3, 12, 12]]
    result = verify(FIND_DUPLICATES, second_occurrence, {"find_duplicates": [long_input]})
    minimal = next(c["minimal"] for c in result["cases"] if c.get("minimal"))
    import ast
    (shrunk,) = ast.literal_eval(minimal["input"])
    assert len(shrunk) == 4 and set(shrunk) <= {1, 2}  # ör. [1, 2, 2, 1]
    assert sorted(ast.literal_eval(minimal["old"])) == sorted(ast.literal_eval(minimal["new"]))
    assert minimal["old"] != minimal["new"]


# --------------------------------------------------------------------------- #
# En kötü durum ölçüm girdisi (erken dönen arama fonksiyonları)
# --------------------------------------------------------------------------- #

from app.verifier import early_return_lines  # noqa: E402

FIND_PAIR = """\
def find_pair(numbers, target):
    for i in range(len(numbers)):
        for j in range(i + 1, len(numbers)):
            if numbers[i] + numbers[j] == target:
                return (i, j)
    return None
"""

FIND_PAIR_GREEN = """\
from bisect import bisect_right

def find_pair(numbers, target):
    positions = {}
    for idx, x in enumerate(numbers):
        positions.setdefault(x, []).append(idx)
    for i, x in enumerate(numbers):
        later = positions.get(target - x)
        if later:
            k = bisect_right(later, i)
            if k < len(later):
                return (i, later[k])
    return None
"""

PAIR_INPUTS = {"find_pair": [[[1, 2, 3, 4], 5], [[], 3], [[5], 10], [[3, 3], 6], [[1, 2], 10]]}


def test_early_return_lines():
    source = (
        "def search(a, t):\n"          # 1
        "    for x in a:\n"            # 2
        "        if x == t:\n"         # 3
        "            return x\n"       # 4  döngü içinde
        "    return None\n"            # 5  döngü dışında
        "\n"
        "def total(a):\n"              # 7
        "    def inner(b):\n"
        "        for y in b:\n"
        "            return y\n"       # iç fonksiyon: sayılmaz
        "    return sum(a)\n"
        "\n"
        "class Index:\n"
        "    def find(self, k):\n"     # 14
        "        while True:\n"
        "            return k\n"       # 16
    )
    assert early_return_lines(source) == {"search": [4], "Index.find": [16]}
    assert early_return_lines("def f(:\n") == {}


def test_auto_benchmark_uses_no_match_input_for_early_return():
    result = verify(FIND_PAIR, FIND_PAIR_GREEN, PAIR_INPUTS)  # LLM benchmark ifadesi yok
    entry = result["benchmark"]["functions"][0]
    assert result["passed"] is True
    assert entry["auto"] is True and entry["worst_case"] is True and entry["note"] is None
    # Eşleşme olmayınca orijinal O(N²) kodun tamamı çalışır: fark yüzlerce kat.
    assert result["benchmark"]["speedup"] > 50


def test_llm_input_with_early_match_is_replaced_by_worst_case():
    reachable = {"find_pair": "[[random.randint(0, 10000) for _ in range(5000)], 10000]"}
    result = verify(FIND_PAIR, FIND_PAIR_GREEN, PAIR_INPUTS, reachable)
    entry = result["benchmark"]["functions"][0]
    assert entry["worst_case"] is True and entry["auto"] is True
    assert "en kötü durum" in entry["note"]
    assert result["benchmark"]["speedup"] > 50


def test_llm_worst_case_input_is_kept():
    unreachable = {"find_pair": "[[random.randint(0, 1000) for _ in range(1500)], -1]"}
    result = verify(FIND_PAIR, FIND_PAIR_GREEN, PAIR_INPUTS, unreachable)
    entry = result["benchmark"]["functions"][0]
    assert entry["worst_case"] is True and entry["auto"] is False and entry["note"] is None


def test_worst_case_not_found_is_reported():
    first = "def first(items):\n    for x in items:\n        return x\n    return None\n"
    result = verify(first, first, {"first": [[[3, 1, 2]], [[5]], [[]], [[1, 1]]]})
    entry = result["benchmark"]["functions"][0]
    assert entry["worst_case"] is False  # boş olmayan her girdide erken döner


def test_functions_without_early_return_have_no_worst_case_flag():
    old = "def total(items):\n    t = 0\n    for x in items:\n        t += x\n    return t\n"
    new = "def total(items):\n    return sum(items)\n"
    result = verify(old, new, {"total": [[[1, 2, 3]], [[]], [[5]], [[4, 4]]]})
    assert result["benchmark"]["functions"][0]["worst_case"] is None


# --------------------------------------------------------------------------- #
# Ölçüm tekrarları arasında önbellek / global durum sıfırlanır
# --------------------------------------------------------------------------- #

from app.verifier import MIN_RELIABLE_SECONDS, _speedup, _summarize_benchmark  # noqa: E402

# Önbelleğe alınmamış her çağrı 20 ms uyur. Önbellek tekrarlar arasında taşınsaydı 2. ve 3.
# tekrar anında döner ve "en iyi" süre ~0 olurdu.
SLOW_CACHED = """\
import time
from functools import lru_cache

@lru_cache(maxsize=None)
def slow(n):
    time.sleep(0.02)
    return n * 2
"""

SLOW_MANUAL_MEMO = """\
import time

_memo = {}

def slow(n):
    if n not in _memo:
        time.sleep(0.02)
        _memo[n] = n * 2
    return _memo[n]
"""

SLOW_INPUTS = {"slow": [[1], [2], [3], [0]]}


@pytest.mark.parametrize("old, new", [
    (SLOW_CACHED, SLOW_CACHED),          # lru_cache: hem eski hem yeni kodda
    (SLOW_MANUAL_MEMO, SLOW_CACHED),     # modül düzeyinde memo sözlüğü (cache_clear ile temizlenemez)
])
def test_cache_is_reset_between_timing_repeats(old, new):
    result = verify(old, new, SLOW_INPUTS, {"slow": "[7]"})
    entry = result["benchmark"]["functions"][0]
    assert result["passed"] is True, result
    # Önbellek doğruluk testlerinde ve önceki tekrarlarda dolmuş olsa da her tekrar sıfırdan başlar.
    assert entry["old_seconds"] >= 0.018
    assert entry["new_seconds"] >= 0.018


def test_lru_cache_fib_speedup_is_realistic():
    naive = "def fib(n):\n    if n < 2:\n        return n\n    return fib(n - 1) + fib(n - 2)\n"
    cached = ("from functools import lru_cache\n\n@lru_cache(maxsize=None)\n" + naive)
    result = verify(naive, cached, {"fib": [[0], [1], [10], [15]]}, {"fib": "[20]"})
    bench = result["benchmark"]
    # Önbellek boşken fib(20) ~20 çağrı yapar: mikro saniyeler mertebesinde, 0 değil.
    assert bench["new_seconds"] >= MIN_RELIABLE_SECONDS
    assert bench["speedup_is_lower_bound"] is False
    assert 10 < bench["speedup"] < 20_000


def test_speedup_guards_against_tiny_times():
    assert _speedup(0.01, 0.0) == (pytest.approx(10_000), True)       # sıfıra bölünmez, alt sınır
    assert _speedup(0.01, 2e-7) == (pytest.approx(10_000), True)
    assert _speedup(0.01, 0.001) == (pytest.approx(10), False)
    assert _speedup(5e-7, 1e-7) == (None, False)                      # ikisi de ölçülemeyecek kadar kısa
    assert _speedup(None, 0.1) == (None, False)


def test_summary_marks_lower_bound():
    entry = {"function": "f", "old_seconds": 0.0074, "new_seconds": 2.9e-7, "outputs_equal": True, "error": None}
    bench = _summarize_benchmark([entry])
    assert bench["speedup"] == pytest.approx(7_400) and bench["speedup_is_lower_bound"] is True


# --------------------------------------------------------------------------- #
# LLM ölçüm girdisi vermezse: liste dışı argümanlarda en büyük test girdisi
# --------------------------------------------------------------------------- #

NAIVE_FIB = "def fib(n):\n    if n < 2:\n        return n\n    return fib(n - 1) + fib(n - 2)\n"
ITER_FIB = "def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n"


def test_scalar_function_is_benchmarked_with_largest_test_input():
    result = verify(NAIVE_FIB, ITER_FIB, {"fib": [[0], [1], [18], [5], [10]]})  # benchmark_input yok
    bench = result["benchmark"]
    assert bench is not None, "fib(n) için ölçüm yapılmalı"
    entry = bench["functions"][0]
    assert entry["auto"] is True and entry["error"] is None and entry["outputs_equal"] is True
    assert "fib(*[18])" in entry["note"]
    assert bench["speedup"] > 10  # O(2^N) -> O(N), n=18


def test_largest_input_uses_all_scalar_arguments():
    old = "def power(base, exp):\n    r = 1\n    for _ in range(exp):\n        r *= base\n    return r\n"
    new = "def power(base, exp):\n    return base ** exp\n"
    result = verify(old, new, {"power": [[2, 3], [3, 40], [10, 2], [5, 0]]})
    assert "power(*[3, 40])" in result["benchmark"]["functions"][0]["note"]


def test_largest_input_for_string_argument():
    old = "def count_a(text):\n    n = 0\n    for ch in text:\n        if ch == 'a':\n            n += 1\n    return n\n"
    new = "def count_a(text):\n    return text.count('a')\n"
    result = verify(old, new, {"count_a": [["abc"], ["banana bandana"], [""], ["a"]]})
    assert "count_a(*['banana bandana'])" in result["benchmark"]["functions"][0]["note"]


def test_inputs_that_fail_in_original_are_not_used_for_benchmark():
    old = "def inv(n):\n    return 1 / n\n"
    result = verify(old, old, {"inv": [[0], [4], [2], [1]]})
    entry = result["benchmark"]["functions"][0]
    assert "inv(*[4])" in entry["note"] and entry["error"] is None


def test_list_functions_still_use_generated_input():
    result = verify(ORIGINAL, GREEN, TEST_INPUTS)  # find_pair, benchmark_input yok
    entry = result["benchmark"]["functions"][0]
    assert entry["auto"] is True
    assert entry["note"] is None or "test girdilerinin en büyüğü" not in entry["note"]



# --------------------------------------------------------------------------- #
# Yan etki farkı: argümanların çağrı sonrası hâli kaydedilir
# --------------------------------------------------------------------------- #

PROCESS_QUEUE = """\
def process_queue(tasks):
    done = []
    while tasks:
        done.append(tasks.pop(0) * 2)
    return done
"""

DEQUE_NO_CLEAR = """\
from collections import deque
def process_queue(tasks):
    queue = deque(tasks)
    done = []
    while queue:
        done.append(queue.popleft() * 2)
    return done
"""

DEQUE_WITH_CLEAR = """\
from collections import deque
def process_queue(tasks):
    queue = deque(tasks)
    tasks.clear()
    done = []
    while queue:
        done.append(queue.popleft() * 2)
    return done
"""

QUEUE_INPUTS = {"process_queue": [[[1, 2, 3]], [[]], [[5]], [[4, 4, 1]]]}


def test_side_effect_difference_records_argument_states():
    result = verify(PROCESS_QUEUE, DEQUE_NO_CLEAR, QUEUE_INPUTS)
    assert result["passed"] is False
    case = result["cases"][0]
    assert case["old"] == case["new"] == "[2, 4, 6]" and case["equal"] is False
    assert case["side_effect"] == [{"name": "tasks", "before": "[1, 2, 3]", "old": "[]", "new": "[1, 2, 3]"}]
    assert "`tasks`" in case["note"]
    # Boş listede iki sürüm de argümanı değiştirmez: eşit.
    assert next(c for c in result["cases"] if c["input"] == "[[]]")["equal"] is True
    # Hata mesajı "sonuçlar farklı" değil, yan etki farkını söyler.
    assert result["error"].startswith("Yan etki farkı")
    assert "orijinalde [], yeni kodda [1, 2, 3]" in result["error"]


def test_preserving_side_effect_passes():
    result = verify(PROCESS_QUEUE, DEQUE_WITH_CLEAR, QUEUE_INPUTS)
    assert result["passed"] is True, result
    assert not any(c.get("side_effect") for c in result["cases"])


def test_side_effect_names_the_changed_argument_among_several():
    old = "def take(items, out):\n    out.extend(items)\n    return len(items)\n"
    new = "def take(items, out):\n    return len(items)\n"
    result = verify(old, new, {"take": [[[1, 2], []], [[3], [9]], [[], []], [[7, 8], [0]]]})
    changes = result["cases"][0]["side_effect"]
    assert [c["name"] for c in changes] == ["out"]
    assert changes[0]["old"] == "[1, 2]" and changes[0]["new"] == "[]"


def test_value_error_message_unchanged_when_outputs_differ():
    wrong = "def process_queue(tasks):\n    return []\n"
    result = verify(PROCESS_QUEUE, wrong, QUEUE_INPUTS)
    assert result["passed"] is False
    assert not (result["error"] or "").startswith("Yan etki farkı")
