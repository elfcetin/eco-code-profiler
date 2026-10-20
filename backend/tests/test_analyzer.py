import textwrap

import pytest

from app.analyzer import analyze


def run(code: str) -> dict:
    return analyze(textwrap.dedent(code))


def codes(code: str) -> set[str]:
    return {f["pattern_code"] for f in run(code)["findings"]}


def complexity_of(code: str, name: str) -> str:
    funcs = {f["name"]: f for f in run(code)["functions"]}
    return funcs[name]["complexity"]


# --------------------------------------------------------------------------- #
# İstenen 4 örnek
# --------------------------------------------------------------------------- #

FIND_DUPLICATES = """
def find_duplicates(items):
    duplicates = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i] == items[j] and items[i] not in duplicates:
                duplicates.append(items[i])
    return duplicates
"""

FIND_PAIR = """
def find_pair(numbers, target):
    for i in range(len(numbers)):
        for j in range(i + 1, len(numbers)):
            if numbers[i] + numbers[j] == target:
                return (i, j)
    return None
"""

BUILD_REPORT = """
def build_report(records):
    report = ""
    for record in records:
        report += f"{record} (toplam {len(records)} kayıt)\\n"
    return report
"""

TOTAL = """
def total(values):
    return sum(values)
"""


def test_find_duplicates():
    result = run(FIND_DUPLICATES)
    found = {f["pattern_code"] for f in result["findings"]}
    assert {"YK-01", "YK-02"} <= found
    assert "YK-05" not in found
    assert result["functions"][0]["complexity"] == "O(N²)"
    # YK-01 dış döngünün satırında, tek kez.
    yk01 = [f for f in result["findings"] if f["pattern_code"] == "YK-01"]
    assert [f["line"] for f in yk01] == [4]


def test_find_pair():
    result = run(FIND_PAIR)
    found = {f["pattern_code"] for f in result["findings"]}
    assert "YK-05" in found
    assert "YK-01" not in found
    assert result["functions"][0]["complexity"] == "O(N²)"


def test_build_report():
    found = codes(BUILD_REPORT)
    assert {"YK-03", "YK-04"} <= found
    assert "YK-01" not in found
    assert complexity_of(BUILD_REPORT, "build_report") == "O(N)"


def test_total_is_clean():
    result = run(TOTAL)
    assert result["syntax_error"] is None
    assert result["findings"] == []
    assert result["functions"][0]["complexity"] in ("O(N)", "O(1)")


# --------------------------------------------------------------------------- #
# Sözdizimi hatası ve çıktı biçimi
# --------------------------------------------------------------------------- #

def test_syntax_error_reports_message_and_line():
    result = analyze("def f(:\n    pass\n")
    assert result["syntax_error"]["line"] == 1
    assert result["syntax_error"]["message"]
    assert result["findings"] == [] and result["functions"] == []


def test_finding_shape():
    finding = run(FIND_DUPLICATES)["findings"][0]
    assert set(finding) == {"line", "pattern_code", "title", "detail", "impact"}
    assert finding["impact"] in ("yüksek", "orta", "düşük")


# --------------------------------------------------------------------------- #
# Karmaşıklık
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "code, expected",
    [
        ("def f(x):\n    return x + 1\n", "O(1)"),
        ("def f(xs):\n    for x in xs:\n        print(x)\n", "O(N)"),
        ("def f(m):\n    for a in m:\n        for b in m:\n            for c in m:\n                print(a, b, c)\n", "O(N³)"),
        ("def f(m):\n    return [a * b for a in m for b in m]\n", "O(N²)"),
        ("def fib(n):\n    if n < 2:\n        return n\n    return fib(n - 1) + fib(n - 2)\n", "O(2^N)"),
        ("def fact(n):\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n", "O(N)"),
    ],
)
def test_complexity(code, expected):
    assert run(code)["functions"][0]["complexity"] == expected


def test_method_complexity_is_reported():
    code = """
    class A:
        def m(self, xs):
            for x in xs:
                pass
    """
    assert complexity_of(code, "A.m") == "O(N)"


# --------------------------------------------------------------------------- #
# YK-01: iç içe döngü
# --------------------------------------------------------------------------- #

def test_yk01_positive_comprehension_inside_loop():
    code = """
    def f(rows, cols):
        out = 0
        for r in rows:
            out += len([c for c in cols if c > r])
        return out
    """
    assert "YK-01" in codes(code)


def test_yk01_reported_once_for_triple_nesting():
    code = """
    def f(m):
        for a in m:
            for b in m:
                for c in m:
                    print(a, b, c)
    """
    yk01 = [f for f in run(code)["findings"] if f["pattern_code"] == "YK-01"]
    assert [f["line"] for f in yk01] == [3]


def test_yk01_negative_sequential_loops():
    code = """
    def f(xs):
        for x in xs:
            print(x)
        while xs:
            xs = xs[1:]
    """
    assert "YK-01" not in codes(code)


# --------------------------------------------------------------------------- #
# YK-02: listede üyelik
# --------------------------------------------------------------------------- #

def test_yk02_positive_list_comprehension_var():
    code = """
    def f(xs, ys):
        allowed = [y for y in ys if y > 0]
        return [x for x in xs if x in allowed]
    """
    assert "YK-02" in codes(code)


def test_yk02_negative_parameter():
    code = """
    def f(xs, allowed):
        return [x for x in xs if x in allowed]
    """
    assert "YK-02" not in codes(code)


def test_yk02_negative_set():
    code = """
    def f(xs):
        seen = set()
        for x in xs:
            if x not in seen:
                seen.add(x)
        return seen
    """
    assert "YK-02" not in codes(code)


def test_yk02_negative_outside_loop():
    code = """
    def f(x):
        items = [1, 2, 3]
        return x in items
    """
    assert "YK-02" not in codes(code)


# --------------------------------------------------------------------------- #
# YK-03: string +=
# --------------------------------------------------------------------------- #

def test_yk03_detail_mentions_cpython():
    yk03 = [f for f in run(BUILD_REPORT)["findings"] if f["pattern_code"] == "YK-03"]
    assert "CPython" in yk03[0]["detail"]


def test_yk03_negative_numeric_accumulator():
    code = """
    def f(xs):
        total = 0
        for x in xs:
            total += x
        return total
    """
    assert "YK-03" not in codes(code)


def test_yk03_negative_outside_loop():
    code = """
    def f(name):
        s = ""
        s += name
        return s
    """
    assert "YK-03" not in codes(code)


# --------------------------------------------------------------------------- #
# YK-04: döngüde değişmeyen len()
# --------------------------------------------------------------------------- #

def test_yk04_positive_while_condition():
    code = """
    def f(xs):
        i = 0
        while i < len(xs):
            i += 1
    """
    assert "YK-04" in codes(code)


def test_yk04_negative_list_modified_in_loop():
    code = """
    def f(stack):
        while len(stack) > 0:
            stack.pop()
    """
    assert "YK-04" not in codes(code)


def test_yk04_negative_range_len_evaluated_once():
    code = """
    def f(xs):
        for i in range(len(xs)):
            print(xs[i])
    """
    assert "YK-04" not in codes(code)


# --------------------------------------------------------------------------- #
# YK-05: two-sum
# --------------------------------------------------------------------------- #

def test_yk05_positive_direct_values():
    code = """
    def f(nums, target):
        for a in nums:
            for b in nums:
                if a + b == target:
                    return a, b
    """
    assert "YK-05" in codes(code)


def test_yk05_negative_single_loop():
    code = """
    def f(nums, target):
        for a in nums:
            if a + 1 == target:
                return a
    """
    assert "YK-05" not in codes(code)


def test_yk05_negative_nested_without_pair_sum():
    code = """
    def f(nums, target):
        for a in nums:
            for b in nums:
                if a * b == target:
                    return a, b
    """
    found = codes(code)
    assert "YK-05" not in found
    assert "YK-01" in found


# --------------------------------------------------------------------------- #
# YK-06: önbelleksiz çoklu özyineleme
# --------------------------------------------------------------------------- #

FIB = """
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
"""


def test_yk06_positive():
    assert "YK-06" in codes(FIB)


def test_yk06_negative_lru_cache():
    code = "from functools import lru_cache\n\n@lru_cache(maxsize=None)" + FIB
    assert "YK-06" not in codes(code)
    assert complexity_of(code, "fib") == "O(N)"


def test_yk06_negative_functools_cache():
    code = "import functools\n\n@functools.cache" + FIB
    assert "YK-06" not in codes(code)


def test_yk06_negative_binary_search_branches():
    code = """
    def search(a, x, lo, hi):
        if lo > hi:
            return -1
        mid = (lo + hi) // 2
        if a[mid] == x:
            return mid
        elif a[mid] < x:
            return search(a, x, mid + 1, hi)
        else:
            return search(a, x, lo, mid - 1)
    """
    assert "YK-06" not in codes(code)


def test_yk06_negative_manual_memo():
    code = """
    def fib(n, memo={}):
        if n in memo:
            return memo[n]
        if n < 2:
            return n
        memo[n] = fib(n - 1, memo) + fib(n - 2, memo)
        return memo[n]
    """
    assert "YK-06" not in codes(code)


# --------------------------------------------------------------------------- #
# YK-07: pop(0) / insert(0, ...)
# --------------------------------------------------------------------------- #

def test_yk07_positive_pop0():
    code = """
    def f(queue):
        while queue:
            item = queue.pop(0)
            print(item)
    """
    assert "YK-07" in codes(code)


def test_yk07_positive_insert0():
    code = """
    def f(xs):
        out = []
        for x in xs:
            out.insert(0, x)
        return out
    """
    assert "YK-07" in codes(code)


def test_yk07_negative_pop_end():
    code = """
    def f(stack):
        while stack:
            stack.pop()
            stack.insert(1, None)
    """
    assert "YK-07" not in codes(code)


# --------------------------------------------------------------------------- #
# YK-08: döngüde sıralama
# --------------------------------------------------------------------------- #

def test_yk08_positive():
    code = """
    def f(stream):
        seen = []
        for x in stream:
            seen.append(x)
            seen.sort()
        return seen
    """
    assert "YK-08" in codes(code)


def test_yk08_negative_sort_before_loop():
    code = """
    def f(xs):
        for x in sorted(xs):
            print(x)
    """
    assert "YK-08" not in codes(code)


# --------------------------------------------------------------------------- #
# YK-09: toplayıcıya list comprehension
# --------------------------------------------------------------------------- #

def test_yk09_positive():
    code = "def f(xs):\n    return sum([x * x for x in xs])\n"
    assert "YK-09" in codes(code)


def test_yk09_negative_generator():
    code = "def f(xs):\n    return any(x > 0 for x in xs)\n"
    assert "YK-09" not in codes(code)


# --------------------------------------------------------------------------- #
# YK-10: döngüde re.compile / open
# --------------------------------------------------------------------------- #

def test_yk10_positive_re_compile():
    code = """
    import re

    def f(lines):
        return [l for l in lines if re.compile(r"\\d+").match(l)]
    """
    assert "YK-10" in codes(code)


def test_yk10_positive_open_same_file():
    code = """
    def f(events):
        for e in events:
            with open("log.txt", "a") as fh:
                fh.write(e)
    """
    assert "YK-10" in codes(code)


def test_yk10_negative_open_different_files():
    code = """
    def f(paths):
        for path in paths:
            with open(path) as fh:
                print(fh.read())
    """
    assert "YK-10" not in codes(code)


def test_yk10_negative_compile_before_loop():
    code = """
    import re

    def f(lines):
        pattern = re.compile(r"\\d+")
        return [l for l in lines if pattern.match(l)]
    """
    assert "YK-10" not in codes(code)
