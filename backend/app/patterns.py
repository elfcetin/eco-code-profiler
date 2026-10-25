"""Onaylı "Yeşil Kod Desenleri" başlangıç verisi.

Asıl kaynak veritabanındaki `green_patterns` tablosudur. Bu liste yalnızca başlangıç
verisidir: backend her açıldığında tabloda OLMAYAN desenler buradan eklenir, mevcut
kayıtların (arayüzden yapılan düzenlemeler dahil) üzerine yazılmaz. Buradaki bir
değişiklik mevcut kurulumlara yansımaz; desenler "Yeşil Kod Desenleri" ekranından
veya /api/patterns uç noktalarından düzenlenir.

Analizci başlık ve etki bilgisini veritabanından alır; bu liste yalnızca katalog
verilmeden çağrıldığında (ör. birim testleri) varsayılan olarak kullanılır.
"""

IMPACT_HIGH = "yüksek"
IMPACT_MEDIUM = "orta"
IMPACT_LOW = "düşük"

GREEN_PATTERNS: list[dict[str, str]] = [
    {
        "code": "YK-01",
        "title": "İç içe döngü",
        "impact": IMPACT_HIGH,
        "anti_pattern": (
            "Bir koleksiyonun her elemanı için başka bir koleksiyonun tamamı dolaşılıyor. "
            "Çalışma süresi O(N²) (veya daha kötü) büyür; çoğu zaman iç döngü yalnızca "
            "bir eşleşme ya da eşitlik araması yapar."
        ),
        "solution": (
            "Aranan tarafı bir kez set/dict'e dönüştürün ve tek geçişte O(1) arama yapın; "
            "gruplama gerekiyorsa dict ile anahtar bazında toplayın. Toplam süre O(N) olur. "
            "İç döngü her eşleşmede bir sonuç üretiyorsa (tekrarlar önemliyse) set yerine "
            "`collections.Counter` ile eşleşme sayısını koruyun."
        ),
        "example_before": (
            "def common(a, b):\n"
            "    result = []\n"
            "    for x in a:\n"
            "        for y in b:\n"
            "            if x == y:\n"
            "                result.append(x)\n"
            "    return result\n"
        ),
        "example_after": (
            "from collections import Counter\n"
            "\n"
            "def common(a, b):\n"
            "    counts = Counter(b)  # her değerin b'de kaç kez geçtiği\n"
            "    result = []\n"
            "    for x in a:\n"
            "        result.extend([x] * counts[x])  # orijinal gibi her eşleşme için bir kez\n"
            "    return result\n"
        ),
    },
    {
        "code": "YK-02",
        "title": "Döngü içinde listede üyelik araması",
        "impact": IMPACT_HIGH,
        "anti_pattern": (
            "Döngü içinde `x in liste` / `x not in liste` kullanılıyor. Listede üyelik "
            "kontrolü doğrusal aramadır (O(N)); döngüyle birlikte O(N²) olur."
        ),
        "solution": (
            "Üyelik kontrolünü set üzerinden yapın (ortalama O(1)). Eleman sırası "
            "gerekiyorsa listeyi korurken yanında bir `seen` set'i tutun."
        ),
        "example_before": (
            "def unique(items):\n"
            "    result = []\n"
            "    for x in items:\n"
            "        if x not in result:\n"
            "            result.append(x)\n"
            "    return result\n"
        ),
        "example_after": (
            "def unique(items):\n"
            "    seen = set()\n"
            "    result = []\n"
            "    for x in items:\n"
            "        if x not in seen:\n"
            "            seen.add(x)\n"
            "            result.append(x)\n"
            "    return result\n"
        ),
    },
    {
        "code": "YK-03",
        "title": "Döngü içinde string birleştirme (+=)",
        "impact": IMPACT_LOW,
        "anti_pattern": (
            "Döngüde bir string'e `+=` ile ekleme yapılıyor. String'ler değişmez olduğu için "
            "her adımda yeni kopya oluşabilir. CPython bunu çoğu durumda kendi içinde "
            "optimize eder, ama bu davranış garanti değildir."
        ),
        "solution": "Parçaları bir listeye ekleyip sonda tek seferde `''.join(parcalar)` kullanın.",
        "example_before": (
            "def render(rows):\n"
            "    out = \"\"\n"
            "    for row in rows:\n"
            "        out += str(row) + \"\\n\"\n"
            "    return out\n"
        ),
        "example_after": (
            "def render(rows):\n"
            "    return \"\".join(str(row) + \"\\n\" for row in rows)\n"
        ),
    },
    {
        "code": "YK-04",
        "title": "Döngü içinde değişmeyen hesaplama",
        "impact": IMPACT_LOW,
        "anti_pattern": (
            "Döngünün her turunda, döngü boyunca sonucu değişmeyen bir ifade "
            "(ör. `len(x)`) yeniden hesaplanıyor."
        ),
        "solution": "Değişmeyen hesaplamayı döngüden önce bir kez yapıp bir değişkende saklayın.",
        "example_before": (
            "def label(items):\n"
            "    out = []\n"
            "    for item in items:\n"
            "        out.append(f\"{item}/{len(items)}\")\n"
            "    return out\n"
        ),
        "example_after": (
            "def label(items):\n"
            "    n = len(items)\n"
            "    return [f\"{item}/{n}\" for item in items]\n"
        ),
    },
    {
        "code": "YK-05",
        "title": "İç içe döngüyle çift toplamı araması (two-sum)",
        "impact": IMPACT_HIGH,
        "anti_pattern": (
            "Toplamı (veya farkı) bir hedefe eşit olan eleman çifti, tüm çiftler iç içe "
            "döngüyle denenerek aranıyor (O(N²))."
        ),
        "solution": (
            "Değerleri indeksleriyle bir dict'te (hash map) tutun ve her eleman için `hedef - x` "
            "değerini O(1) sürede arayın. Birden fazla çift olabiliyorsa orijinalin döndürdüğü çifti "
            "(en küçük i, sonra en küçük j) korumak için her değerin indeks listesini tutup `bisect` ile "
            "i'den sonraki ilk j'yi bulun (O(N log N)). İlk tamamlanan çifti döndüren tek geçişli "
            "sürüm FARKLI bir çift döndürebilir; yalnızca tek çözüm garanti ise kullanın."
        ),
        "example_before": (
            "def find_pair(nums, target):\n"
            "    for i in range(len(nums)):\n"
            "        for j in range(i + 1, len(nums)):\n"
            "            if nums[i] + nums[j] == target:\n"
            "                return (i, j)\n"
            "    return None\n"
        ),
        "example_after": (
            "from bisect import bisect_right\n"
            "\n"
            "def find_pair(nums, target):\n"
            "    positions = {}  # değer -> artan indeks listesi\n"
            "    for j, x in enumerate(nums):\n"
            "        positions.setdefault(x, []).append(j)\n"
            "    for i, x in enumerate(nums):\n"
            "        later = positions.get(target - x)\n"
            "        if later:\n"
            "            k = bisect_right(later, i)  # i'den sonraki ilk indeks\n"
            "            if k < len(later):\n"
            "                return (i, later[k])\n"
            "    return None\n"
        ),
    },
    {
        "code": "YK-06",
        "title": "Önbelleksiz çoklu özyineleme",
        "impact": IMPACT_HIGH,
        "anti_pattern": (
            "Fonksiyon kendini bir çağrıda iki veya daha fazla kez çağırıyor ve aynı alt "
            "problemleri tekrar tekrar hesaplıyor; süre üstel (O(2^N)) büyüyebilir."
        ),
        "solution": (
            "Saf (yan etkisiz, hashlenebilir argümanlı) fonksiyonlarda `@functools.lru_cache` "
            "veya `@functools.cache` ekleyin; ya da çözümü iteratif (bottom-up) yazın."
        ),
        "example_before": (
            "def fib(n):\n"
            "    if n < 2:\n"
            "        return n\n"
            "    return fib(n - 1) + fib(n - 2)\n"
        ),
        "example_after": (
            "def fib(n):\n"
            "    a, b = 0, 1\n"
            "    for _ in range(n):\n"
            "        a, b = b, a + b\n"
            "    return a\n"
        ),
    },
    {
        "code": "YK-07",
        "title": "Döngü içinde listenin başından ekleme/çıkarma",
        "impact": IMPACT_HIGH,
        "anti_pattern": (
            "Döngüde `liste.pop(0)` veya `liste.insert(0, x)` kullanılıyor. Her çağrı tüm "
            "elemanları kaydırır (O(N)); döngüyle O(N²) olur."
        ),
        "solution": (
            "Kuyruk veya çift uçlu kullanım için `collections.deque` ve O(1) çalışan "
            "`popleft()` / `appendleft()` metotlarını kullanın. Orijinal kod girdi listesini "
            "boşaltıyorsa (yan etki), deque'ya kopyaladıktan sonra `liste.clear()` ile aynı "
            "davranışı koruyun."
        ),
        "example_before": (
            "def drain(tasks):\n"
            "    done = []\n"
            "    while tasks:\n"
            "        done.append(tasks.pop(0))\n"
            "    return done\n"
        ),
        "example_after": (
            "from collections import deque\n"
            "\n"
            "def drain(tasks):\n"
            "    queue = deque(tasks)\n"
            "    tasks.clear()  # orijinal gibi girdi listesini boşalt (yan etkiyi koru)\n"
            "    done = []\n"
            "    while queue:\n"
            "        done.append(queue.popleft())\n"
            "    return done\n"
        ),
    },
    {
        "code": "YK-08",
        "title": "Döngü içinde sıralama",
        "impact": IMPACT_HIGH,
        "anti_pattern": (
            "Döngünün her turunda `.sort()` veya `sorted()` çağrılıyor; her biri O(N log N) "
            "olduğundan toplam maliyet O(N² log N)'e çıkar."
        ),
        "solution": (
            "Sıralı veri yalnızca döngü bittikten sonra gerekiyorsa (ör. en büyük k eleman) "
            "sıralamayı döngüden sonra bir kez yapın. Her adımda yalnızca en küçük/en büyük "
            "eleman gerekiyorsa `heapq`, her adımda tüm sıralı liste gerekiyorsa `bisect.insort` "
            "kullanın. Heap sıralı DEĞİLDİR (yalnızca heap[0] en küçüktür); sıralı sonuç "
            "döndürülecekse `sorted(...)` kullanın."
        ),
        "example_before": (
            "def running_min(stream):\n"
            "    seen, out = [], []\n"
            "    for x in stream:\n"
            "        seen.append(x)\n"
            "        seen.sort()\n"
            "        out.append(seen[0])\n"
            "    return out\n"
            "\n"
            "\n"
            "def top_three(values):\n"
            "    best = []\n"
            "    for v in values:\n"
            "        best.append(v)\n"
            "        best.sort()\n"
            "    return best[-3:]\n"
        ),
        "example_after": (
            "import heapq\n"
            "\n"
            "def running_min(stream):\n"
            "    heap, out = [], []\n"
            "    for x in stream:\n"
            "        heapq.heappush(heap, x)\n"
            "        out.append(heap[0])  # her adımda yalnızca en küçük gerekiyor: heap\n"
            "    return out\n"
            "\n"
            "\n"
            "def top_three(values):\n"
            "    # Sıralı veri yalnızca sonda gerekiyor: döngüde değil, bir kez sırala.\n"
            "    return sorted(values)[-3:]\n"
        ),
    },
    {
        "code": "YK-09",
        "title": "Toplayıcı fonksiyona list comprehension verilmesi",
        "impact": IMPACT_LOW,
        "anti_pattern": (
            "`sum`, `any`, `all`, `min`, `max` gibi fonksiyonlara `[...]` list comprehension "
            "veriliyor; tüm ara liste gereksiz yere bellekte oluşturuluyor ve any/all erken "
            "sonlanamıyor."
        ),
        "solution": "Köşeli parantezleri kaldırarak generator ifadesi verin: `sum(x for x in xs)`.",
        "example_before": (
            "def has_negative(xs):\n"
            "    return any([x < 0 for x in xs])\n"
        ),
        "example_after": (
            "def has_negative(xs):\n"
            "    return any(x < 0 for x in xs)\n"
        ),
    },
    {
        "code": "YK-10",
        "title": "Döngü içinde re.compile()/open()",
        "impact": IMPACT_MEDIUM,
        "anti_pattern": (
            "Döngü içinde aynı argümanlarla `re.compile(...)` veya `open(...)` çağrılıyor; "
            "her turda gereksiz derleme veya dosya açma/kapama (sistem çağrısı) maliyeti oluşur."
        ),
        "solution": (
            "Deseni döngüden önce bir kez derleyin; dosyayı döngüden önce bir kez açıp "
            "döngü boyunca aynı dosya tanıtıcısını kullanın."
        ),
        "example_before": (
            "import re\n"
            "\n"
            "def count_numbers(lines):\n"
            "    return sum(1 for line in lines if re.compile(r\"\\d+\").search(line))\n"
        ),
        "example_after": (
            "import re\n"
            "\n"
            "NUMBER = re.compile(r\"\\d+\")\n"
            "\n"
            "def count_numbers(lines):\n"
            "    return sum(1 for line in lines if NUMBER.search(line))\n"
        ),
    },
]

PATTERNS_BY_CODE: dict[str, dict[str, str]] = {p["code"]: p for p in GREEN_PATTERNS}

# Örneklerin eşdeğerlik kontrolü için başlangıç test girdileri: desen kodu -> {fonksiyon: [[argümanlar], ...]}.
# Tekrarlar, boş/tek eleman ve kenar durumlar içerir; doğrulayıcı ayrıca sıralı/ters/rastgele girdiler türetir.
# Veritabanında `example_inputs` olarak saklanır ve Desenler ekranından düzenlenebilir.
EXAMPLE_INPUTS: dict[str, dict[str, list]] = {
    "YK-01": {"common": [[[1, 2, 3], [2, 3, 4]], [[1, 1, 2], [1, 1, 5]], [[], [1]], [[3, 1, 3], [3]], [["a", "b"], ["b", "b"]]]},
    "YK-02": {"unique": [[[3, 1, 3, 2, 1]], [[]], [[7]], [["b", "a", "b"]]]},
    "YK-03": {"render": [[[1, 2, 3]], [[]], [["a"]], [[0, -1, 2]]]},
    "YK-04": {"label": [[["a", "b", "c"]], [[]], [[1]], [[5, 5]]]},
    "YK-05": {"find_pair": [[[1, 2, 3, 4], 5], [[3, 3, 4], 6], [[], 1], [[5], 10], [[1, 4, 2, 3, 2], 5]]},
    "YK-06": {"fib": [[0], [1], [2], [10], [15]]},
    "YK-07": {"drain": [[[1, 2, 3]], [[]], [[5]], [[4, 4, 1]]]},
    "YK-08": {
        "running_min": [[[5, 3, 8, 1, 4]], [[]], [[2]], [[3, 3, 1, 1]]],
        "top_three": [[[50, 90, 70, 80]], [[]], [[5]], [[3, 3, 1]], [[1, 2]]],
    },
    "YK-09": {"has_negative": [[[1, -2, 3]], [[]], [[0, 1]], [[-1]]]},
    "YK-10": {"count_numbers": [[["a1", "b", "22c"]], [[]], [["x"]], [["7", "8", "9"]]]},
}

