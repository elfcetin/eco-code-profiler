import os
import time

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
    assert "yan etki" in result["cases"][0]["note"]


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
