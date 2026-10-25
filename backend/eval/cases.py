"""Değerlendirme seti: sistemin daha önce görmediği kodlar (test bölümü).

KURAL: Bu set, sonuçlara bakılmadan önce yazılıp donduruldu. Buradaki kodlara göre desen,
istem veya geri bildirim DÜZELTİLMEZ; set yalnızca ölçüm ve raporlama içindir. İyileştirme
denemeleri için ayrı bir geliştirme seti kullanılmalıdır.

Her kayıt:
- id: benzersiz ad
- expected: kodda bulunması beklenen desen(ler)
- code: orijinal kod
- hidden: gizli testler {fonksiyon: [[argümanlar], ...]} — LLM'in ve doğrulayıcının görmediği,
  daha zorlayıcı girdiler (tekrarlar, negatifler, boş/tek eleman, büyük girdiler). "Optimize
  edildi" sonucunun gerçekten doğru olup olmadığını (yanlış onay) bağımsız olarak denetler.
"""

import random

_rng = random.Random(2026)


def _ints(n, lo=-50, hi=50):
    return [_rng.randint(lo, hi) for _ in range(n)]


def _words(n, pool=("ali", "veli", "ayşe", "fatma", "can", "ece", "deniz", "Ada", "ALİ")):
    return [_rng.choice(pool) for _ in range(n)]


CASES = [
    # ------------------------------------------------------------------ YK-01
    {
        "id": "tag_known_words",
        "expected": ["YK-01"],
        "code": '''\
def tag_known_words(words, dictionary):
    flags = []
    for w in words:
        found = False
        for d in dictionary:
            if w == d:
                found = True
                break
        flags.append(found)
    return flags
''',
        "hidden": {"tag_known_words": [
            [[], ["a"]], [["a"], []], [["a", "a", "b"], ["a"]], [_words(300), _words(80)],
            [["x", "y"], ["y", "y", "x"]],
        ]},
    },
    {
        "id": "total_by_name",
        "expected": ["YK-01"],
        "code": '''\
def total_by_name(names, records):
    totals = []
    for name in names:
        total = 0
        for record in records:
            if record[0] == name:
                total += record[1]
        totals.append(total)
    return totals
''',
        "hidden": {"total_by_name": [
            [[], [["a", 1]]], [["a"], []], [["a", "a"], [["a", 2], ["a", 3], ["b", 9]]],
            [_words(50), [[w, v] for w, v in zip(_words(400), _ints(400))]],
            [["z"], [["a", 1]]],
        ]},
    },
    # ------------------------------------------------------------------ YK-02
    {
        "id": "merge_unique",
        "expected": ["YK-02"],
        "code": '''\
def merge_unique(first, second):
    merged = []
    for item in first + second:
        if item not in merged:
            merged.append(item)
    return merged
''',
        "hidden": {"merge_unique": [
            [[], []], [[1, 1, 1], []], [[3, 2, 1], [1, 2, 3, 4]], [_ints(500, 0, 60), _ints(500, 30, 90)],
            [["b", "a"], ["a", "c", "b"]],
        ]},
    },
    {
        "id": "missing_ids",
        "expected": ["YK-02"],
        "code": '''\
def missing_ids(expected, received):
    seen = []
    for r in received:
        seen.append(r)
    missing = []
    for e in expected:
        if e not in seen:
            missing.append(e)
    return missing
''',
        "hidden": {"missing_ids": [
            [[], [1]], [[1, 2, 2, 3], []], [[5, 5, 6], [5]], [_ints(600, 0, 400), _ints(600, 0, 400)],
            [["a", "b"], ["b"]],
        ]},
    },
    # ------------------------------------------------------------------ YK-03
    {
        "id": "to_csv_line",
        "expected": ["YK-03"],
        "code": '''\
def to_csv_line(values):
    line = ""
    for i, v in enumerate(values):
        if i > 0:
            line += ","
        line += str(v)
    return line
''',
        "hidden": {"to_csv_line": [[[]], [[1]], [[1, "a", 2.5, None, True]], [_ints(800)], [["", ""]]]},
    },
    {
        "id": "repeat_with_dash",
        "expected": ["YK-03"],
        "code": '''\
def repeat_with_dash(word, times):
    out = ""
    for _ in range(times):
        out += word + "-"
    return out
''',
        "hidden": {"repeat_with_dash": [["ab", 0], ["", 3], ["x", 1], ["çok", 2000], ["a", -2]]},
    },
    # ------------------------------------------------------------------ YK-04
    {
        "id": "normalize",
        "expected": ["YK-04"],
        "code": '''\
def normalize(values):
    out = []
    for v in values:
        out.append(v / len(values))
    return out
''',
        "hidden": {"normalize": [[[]], [[4]], [[1, 2, 3]], [_ints(1000)], [[0, 0]]]},
    },
    {
        "id": "label_steps",
        "expected": ["YK-04"],
        "code": '''\
def label_steps(steps):
    labels = []
    for i, step in enumerate(steps):
        labels.append(f"{step} ({i + 1}/{len(steps)})")
    return labels
''',
        "hidden": {"label_steps": [[[]], [["kur"]], [["a", "b", "a"]], [_words(700)]]},
    },
    # ------------------------------------------------------------------ YK-05
    {
        "id": "has_pair_with_sum",
        "expected": ["YK-05"],
        "code": '''\
def has_pair_with_sum(nums, target):
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target:
                return True
    return False
''',
        "hidden": {"has_pair_with_sum": [
            [[], 0], [[5], 10], [[5, 5], 10], [[1, 2, 3], 7], [_ints(1500), 10_000], [_ints(1500), 3],
            [[-3, 3, 0], 0],
        ]},
    },
    {
        "id": "count_pairs_with_difference",
        "expected": ["YK-05"],
        "code": '''\
def count_pairs_with_difference(nums, k):
    count = 0
    for i in range(len(nums)):
        for j in range(len(nums)):
            if i != j and nums[i] - nums[j] == k:
                count += 1
    return count
''',
        "hidden": {"count_pairs_with_difference": [
            [[], 1], [[1, 1, 1], 0], [[1, 2, 3, 4], 1], [[4, 1, 4, 1], -3], [_ints(700, 0, 30), 2],
            [_ints(700, 0, 30), 0],
        ]},
    },
    # ------------------------------------------------------------------ YK-06
    {
        "id": "count_grid_paths",
        "expected": ["YK-06"],
        "code": '''\
def count_grid_paths(rows, cols):
    if rows == 1 or cols == 1:
        return 1
    return count_grid_paths(rows - 1, cols) + count_grid_paths(rows, cols - 1)
''',
        "hidden": {"count_grid_paths": [[1, 1], [1, 9], [2, 2], [3, 7], [10, 10], [13, 12]]},
    },
    {
        "id": "tribonacci",
        "expected": ["YK-06"],
        "code": '''\
def tribonacci(n):
    if n == 0 or n == 1:
        return 0
    if n == 2:
        return 1
    return tribonacci(n - 1) + tribonacci(n - 2) + tribonacci(n - 3)
''',
        "hidden": {"tribonacci": [[0], [1], [2], [3], [10], [21]]},
    },
    # ------------------------------------------------------------------ YK-07
    {
        "id": "reverse_copy",
        "expected": ["YK-07"],
        "code": '''\
def reverse_copy(items):
    out = []
    for x in items:
        out.insert(0, x)
    return out
''',
        "hidden": {"reverse_copy": [[[]], [[1]], [[1, 2, 2, 3]], [_ints(3000)], [["a", None, 1]]]},
    },
    {
        "id": "rotate_left",
        "expected": ["YK-07"],
        "code": '''\
def rotate_left(items, k):
    data = list(items)
    for _ in range(k):
        data.append(data.pop(0))
    return data
''',
        "hidden": {"rotate_left": [
            [[1, 2, 3], 0], [[1, 2, 3], 1], [[1, 2, 3], 7], [[], 0], [[], 2], [_ints(500), 1200], [[5], 3],
        ]},
    },
    # ------------------------------------------------------------------ YK-08
    {
        "id": "median_so_far",
        "expected": ["YK-08"],
        "code": '''\
def median_so_far(stream):
    seen = []
    medians = []
    for x in stream:
        seen.append(x)
        seen.sort()
        medians.append(seen[len(seen) // 2])
    return medians
''',
        "hidden": {"median_so_far": [[[]], [[7]], [[3, 1, 2]], [[5, 5, 5, 1]], [_ints(1500)]]},
    },
    {
        "id": "rank_names",
        "expected": ["YK-08"],
        "code": '''\
def rank_names(names):
    ranked = []
    for name in names:
        ranked.append(name.lower())
        ranked = sorted(ranked)
    return ranked
''',
        "hidden": {"rank_names": [[[]], [["Zeynep"]], [["b", "A", "a", "B"]], [_words(900)]]},
    },
    # ------------------------------------------------------------------ YK-09
    {
        "id": "total_price",
        "expected": ["YK-09"],
        "code": '''\
def total_price(items):
    return sum([item["price"] * item["qty"] for item in items])
''',
        "hidden": {"total_price": [
            [[]], [[{"price": 2.5, "qty": 4}]], [[{"price": p, "qty": q} for p, q in zip(_ints(500, 0, 99), _ints(500, 0, 9))]],
        ]},
    },
    {
        "id": "all_positive",
        "expected": ["YK-09"],
        "code": '''\
def all_positive(values):
    return all([v > 0 for v in values])
''',
        "hidden": {"all_positive": [[[]], [[1, 2, 3]], [[1, -1, 2]], [[0]], [_ints(2000, 1, 100)]]},
    },
    # ------------------------------------------------------------------ YK-10
    {
        "id": "extract_emails",
        "expected": ["YK-10"],
        "code": '''\
import re

def extract_emails(lines):
    found = []
    for line in lines:
        found.extend(re.compile(r"[\\w.]+@[\\w.]+").findall(line))
    return found
''',
        "hidden": {"extract_emails": [
            [[]], [["iletişim: ali@ornek.com, veli@ornek.org"]], [["yok", "", "a@b c@d"]],
            [[f"kullanıcı{i}@site.com metin {i}" for i in range(400)]],
        ]},
    },
    {
        "id": "count_word",
        "expected": ["YK-10"],
        "code": '''\
import re

def count_word(lines, word):
    total = 0
    for line in lines:
        total += len(re.compile(r"\\b" + re.escape(word) + r"\\b").findall(line))
    return total
''',
        "hidden": {"count_word": [
            [[], "a"], [["kedi köpek kedi"], "kedi"], [["kediler kedi"], "kedi"], [["a.b a.b"], "a.b"],
            [[" ".join(_words(30)) for _ in range(300)], "ali"],
        ]},
    },
]
