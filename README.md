# Eco-Code Profiler

🎥 **Ekran kaydı:** <https://drive.google.com/file/d/1zd_66iX9i9wUBRGcivbW5X4tUC-2_Nck/view?usp=sharing>

Kapalı ağda (air-gapped) çalışan kurumlar için **algoritmik enerji israfı** analiz paneli.

Geliştirici Python kodunu yapıştırır. Sistem:

1. Kodu **AST ile statik olarak analiz eder** ve gereksiz iş yapan yapıları tespit eder (ör. O(N²) iç içe döngüler, döngüde listede arama, önbelleksiz özyineleme).
2. Tespit edilen desenlere karşılık gelen **onaylı "Yeşil Kod Desenleri"ni** veritabanından getirir.
3. Kodu **yerel bir LLM**'e (Ollama) yeniden yazdırır. Modele yalnızca bu desenlerin çözüm ve örnekleri verilir ve yalnızca bunları kullanması istenir. Fonksiyon adlarının ve imzalarının değişmediği yanıt gelince denetlenir.
4. Eski ve yeni kodu **yalıtılmış bir alt süreçte çalıştırır**, aynı girdilerde aynı sonucu verdiklerini doğrular ve **çalışma sürelerini ölçer**.

Doğrulamadan geçemeyen kod "optimize edildi" olarak sunulmaz. Doğrulama başarısız olursa hata ayrıntısı (en küçük karşı örnek dahil) LLM'e geri bildirim olarak verilip bir kez daha denenir. Ayrıntılar için [Doğrulama nasıl çalışır](#doğrulama-nasıl-çalışır) bölümüne bakın.

> Ölçülen değer **çalışma süresidir**, enerji değildir. Sistem Watt/kWh tahmini üretmez. Daha kısa CPU süresi daha az enerji anlamına gelir, ancak bu sistem enerjiyi doğrudan ölçmez.

---

## Mimari

```
 ┌────────────────────────────┐
 │  Tarayıcı (React + Vite)   │  Analiz · Yeşil Kod Desenleri · Geçmiş
 └─────────────┬──────────────┘
               │ HTTP /api/*
 ┌─────────────▼──────────────────────────────────────────────────────┐
 │  FastAPI  (backend/app/main.py)                                    │
 │                                                                    │
 │   analyzer.py ── AST ile desen tespiti (YK-01…YK-10)               │
 │                  + fonksiyon başına karmaşıklık tahmini            │
 │   rag.py ─────── tespit edilen desen kodlarının kayıtlarını getirir│
 │   llm.py ─────── istem + JSON doğrulama ──────────┐                │
 │   verifier.py ── alt süreçte eşdeğerlik + timeit  │                │
 │   db.py ──────── SQLAlchemy 2.0                   │                │
 └──────┬───────────────────────┬────────────────────┼────────────────┘
        │                       │                    │
 ┌──────▼───────┐   ┌───────────▼──────────┐  ┌──────▼──────────────────┐
 │ PostgreSQL   │   │ python -I alt süreci │  │ Ollama (yerel, varsayılan│
 │ (geliştirme: │   │ geçici dizin, 60 sn, │  │ qwen2.5-coder:7b)        │
 │  SQLite)     │   │ bellek/CPU sınırı    │  │ — veya Gemini API        │
 └──────────────┘   └──────────────────────┘  └─────────────────────────┘
```

**`POST /api/optimize` akışı**

```
kod ─► analyzer ─► bulgu yok? ──evet──► status="clean"  (LLM çağrılmaz)
                       │ hayır
                       ▼
                rag.retrieve(desen kodları)
                       ▼
                llm.optimize ─► verifier.verify ─► geçti? ──evet──► status="optimized"
                       ▲                               │ hayır
                       └──── geri bildirimle 1 tekrar ◄┘ ──(yine geçmezse)──► status="failed"
                       ▼
                analyzer(yeşil kod) ─► analysis_runs tablosuna kayıt
```

### Doğrulama nasıl çalışır

LLM çıktısına güvenilmez; her yeniden yazım önce süzülür, sonra yalıtılmış bir alt süreçte orijinalle karşılaştırılır.

**1. LLM yanıtının kontrolü ve onarımı** (`llm.py`). Küçük yerel modellerin sık yaptığı, anlamı değiştirmeyen hatalar otomatik düzeltilir; her düzeltme yanıttaki `warnings` listesine yazılır:

| Durum | Ne yapılır |
|---|---|
| Geçersiz JSON, eksik `green_code`, sözdizimi hatası | Reddedilir, geri bildirimle yeniden denenir |
| Fonksiyon eksik, parametre sayısı/varsayılanı değişmiş | Reddedilir |
| Yalnızca parametre adları değişmiş (ör. desen örneğindeki `nums` kopyalanmış) | Adlar orijinaline geri çevrilir (çakışma yoksa) |
| Tür ipucu eklenmiş (`numbers: list`) | İmza değişikliği sayılmaz |
| String içindeki `\n` JSON'da bozulmuş ("unterminated string") | Kaçış onarılır |
| Test girdisine beklenen çıktı eklenmiş (`[girdi, beklenen]`) | Fazladan eleman atılır |
| Test girdisi imzaya uymuyor | Atlanır; hiçbiri uymuyorsa reddedilir |

**2. Eşdeğerlik testi** (`verifier.py`). Her fonksiyon şu girdilerle hem eski hem yeni kodda, `deepcopy`'lenmiş argümanlarla çağrılır:

- LLM'in ürettiği test girdileri (en az 4),
- **sistemin türettiği girdiler** (LLM'den bağımsız): her girdinin liste argümanları azalan sıralı ve ters çevrilmiş hâlleri, ayrıca örnek girdiden üretilen bol tekrarlı **3 rastgele girdi** (40 eleman).

Sonuçlar **tür dahil** karşılaştırılır (`1` ile `1.0` farklıdır). Aynı tür hata fırlatmak eşit sayılır. Fonksiyonların argümanları farklı biçimde değiştirmesi (yan etki farkı) de uyuşmazlıktır. Hiçbir girdi orijinal kodda hatasız çalışmadıysa test anlamsız kabul edilir ve geçmez.

Türetilmiş girdiler önemlidir. Gerçek denemelerde LLM'in seçtiği küçük girdilerde tesadüfen doğru çıkan sıra hataları (ör. `list(set(...))`) yalnızca bunlarla yakalandı.

**3. Ölçüm.** LLM'in verdiği benchmark ifadesi (~5000 eleman) aynı rastgele tohumla üretilir ve her iki sürüm `timeit` ile ölçülür (3 tekrarın en iyisi). LLM ifade vermezse örnek girdiden 2000 elemanlı **otomatik girdi** üretilir; bu girdi en kötü durumu temsil etmeyebilir ve arayüzde öyle belirtilir. Benchmark girdisinde de sonuçlar karşılaştırılır. Hata veren ya da farklı sonuç üreten ölçümler hızlanma hesabına katılmaz.

**4. Geri bildirim.** Doğrulama başarısız olursa, uyuşmayan girdi farkı koruyarak **en küçük karşı örneğe** indirilir (ör. 40 elemanlı liste → `[1, 2, 2, 1]`: beklenen `[1, 2]`, üretilen `[2, 1]`). Sonuçların yalnızca sırası farklıysa LLM'e "set'in sırası tanımsızdır; dict/Counter kullan" ipucu eklenir. Bu geri bildirimle bir kez daha denenir. Karşı örnek arayüzdeki eşdeğerlik tablosunda da gösterilir.

### Klasör yapısı

```
.
├── backend/
│   ├── app/
│   │   ├── main.py        FastAPI uç noktaları, CORS, statik frontend
│   │   ├── analyzer.py    AST analizi (LLM yok)
│   │   ├── patterns.py    Yeşil Kod Desenleri başlangıç verisi (tek kaynak)
│   │   ├── db.py          Modeller: green_patterns, analysis_runs
│   │   ├── rag.py         Kural tabanlı desen getirme
│   │   ├── llm.py         Ollama / Gemini sağlayıcıları
│   │   ├── verifier.py    Alt süreçte doğrulama ve ölçüm
│   │   └── config.py      Ortam değişkenleri
│   ├── tests/             pytest testleri
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/              React + Vite arayüzü
├── docker-compose.yml     PostgreSQL + Ollama + backend
└── README.md
```

### Yeşil Kod Desenleri

| Kod   | Tespit edilen sorun                              | Çözüm                                   | Etki   |
|-------|--------------------------------------------------|-----------------------------------------|--------|
| YK-01 | İç içe döngü                                     | set/dict ile tek geçiş                  | yüksek |
| YK-02 | Döngüde listede `in` / `not in`                  | `set` ile üyelik kontrolü               | yüksek |
| YK-03 | Döngüde string `+=`                              | `"".join(...)`                          | düşük  |
| YK-04 | Döngüde değişmeyen `len(x)`                      | Döngü dışına al                         | düşük  |
| YK-05 | İç içe döngüyle two-sum (`a + b == hedef`)       | Hash map (+ sıra için `bisect`)         | yüksek |
| YK-06 | Önbelleksiz çoklu özyineleme                     | `functools.lru_cache` veya iteratif     | yüksek |
| YK-07 | Döngüde `pop(0)` / `insert(0, …)`                | `collections.deque`                     | yüksek |
| YK-08 | Döngüde `.sort()` / `sorted()`                   | Bir kez sırala veya `heapq`             | yüksek |
| YK-09 | `sum/any/all/min/max([...])`                     | Generator ifadesi                       | düşük  |
| YK-10 | Döngüde `re.compile()` / `open()`                | Döngü dışına al                         | orta   |

Desenlerin tam metni ve önce/sonra örnekleri arayüzdeki **Yeşil Kod Desenleri** sekmesinde ve `GET /api/patterns` ucunda bulunur.

Onaylı desenlerin tek kaynağı `backend/app/patterns.py` dosyasıdır. Uygulama her açılışta `green_patterns` tablosunu bu dosyayla **eşitler**: eksik desenler eklenir, içeriği değişmiş olanlar güncellenir. Böylece katalogdaki düzeltmeler mevcut kurulumlara da ulaşır. Dosyada olmayan (kuruma özel eklenmiş) kayıtlara dokunulmaz; ancak YK-01…YK-10 kodlu kayıtlarda veritabanında yapılan elle düzenlemeler bir sonraki açılışta geri alınır.

> Örnekler önemlidir: modeller desen örneklerini sık sık birebir kopyalar. YK-05'in ilk sürümündeki örnek, birden fazla çift olduğunda orijinalden farklı bir çift döndürüyordu; eşdeğerlik testi bunu yakaladı ve örnek, sırayı koruyan sürümle değiştirildi. Yeni bir desen eklerken örneği orijinalle rastgele girdilerde karşılaştırın.

---

## Kurulum

### Seçenek A — Docker Compose (önerilen)

Gereksinim: Docker ve Docker Compose v2.

```bash
docker compose up -d --build
```

- Arayüz: <http://localhost:8000>
- API belgeleri (Swagger): <http://localhost:8000/docs>

İlk çalıştırmada `ollama-pull` servisi `qwen2.5-coder:7b` modelini indirir (~4,7 GB). İndirme bitene kadar üst bardaki LLM göstergesi kırmızı kalır. İlerlemeyi şu komutla izleyebilirsiniz:

```bash
docker compose logs -f ollama-pull
```

NVIDIA GPU kullanmak için `docker-compose.yml` içindeki `ollama` servisinde yer alan `deploy` bloğunun yorumunu kaldırın. GPU olmadan model CPU üzerinde çalışır; tek bir optimizasyon birkaç dakika sürebilir (`LLM_TIMEOUT` varsayılanı 300 sn).

### Seçenek B — Yerel geliştirme

Gereksinimler: Python 3.11+, Node.js 20+, Ollama.

#### 1. Ollama

```bash
# macOS
brew install ollama            # veya https://ollama.com/download
# Linux
curl -fsSL https://ollama.com/install.sh | sh

ollama serve                   # masaüstü uygulaması kuruluysa zaten çalışıyordur
ollama pull qwen2.5-coder:7b
ollama list                    # modelin indiğini doğrulayın
```

Başka bir model kullanmak için `OLLAMA_MODEL` değişkenini ayarlayın (ör. `OLLAMA_MODEL=llama3:8b uvicorn app.main:app --reload`). Bkz. [Model seçimi](#model-seçimi).

#### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload  # http://localhost:8000
```

`DATABASE_URL` verilmezse `backend/eco_profiler.db` adlı bir SQLite dosyası kullanılır. Tablolar ve desen verisi ilk açılışta otomatik oluşturulur.

Testleri çalıştırmak için:

```bash
cd backend
.venv/bin/pytest
```

Testler LLM'i taklit eder (mock); Ollama'nın çalışması gerekmez. Doğrulayıcı testleri gerçek alt süreç başlatır.

#### 3. Frontend

```bash
cd frontend
npm install
npm run dev                    # http://localhost:5173
```

Geliştirme sunucusu `/api` isteklerini Vite proxy üzerinden `http://localhost:8000` adresine yönlendirir.

Tek sunucuyla çalıştırmak için önce `npm run build` komutunu çalıştırın. Backend, `frontend/dist` klasörü varsa onu kök adresten (<http://localhost:8000>) sunar. Bu kontrol backend açılırken yapıldığından, build sonrası backend'i yeniden başlatın.

### Kapalı ağ (air-gapped) kurulumu

Kapalı ağdaki sunucuda internet olmadığı için imajlar ve model, internete bağlı bir makinede hazırlanıp taşınır.

```bash
# İnternete bağlı makinede
docker compose build
docker compose pull postgres ollama
docker compose up -d ollama && docker compose run --rm ollama-pull
docker save -o eco-images.tar eco-profiler-backend postgres:16-alpine ollama/ollama:latest
docker run --rm -v eco-profiler_ollama:/data -v "$PWD":/out alpine \
  tar czf /out/ollama-models.tgz -C /data .

# Kapalı ağdaki sunucuda
docker load -i eco-images.tar
docker volume create eco-profiler_ollama
docker run --rm -v eco-profiler_ollama:/data -v "$PWD":/in alpine \
  tar xzf /in/ollama-models.tgz -C /data
docker compose up -d --no-build postgres ollama backend
```

Compose proje adı `eco-profiler` olarak sabitlendiği için imaj ve volume adları yukarıdaki gibidir (`docker images`, `docker volume ls` ile kontrol edebilirsiniz). Docker kullanmayan kurulumlarda `~/.ollama/models` klasörünü aynı yola kopyalamak yeterlidir.

---

## Ortam değişkenleri

Değişkenler `backend/app/config.py` tarafından okunur. Örnek dosya: `backend/.env.example`.

| Değişken         | Varsayılan                          | Açıklama |
|------------------|-------------------------------------|----------|
| `DATABASE_URL`   | `sqlite:///backend/eco_profiler.db` | SQLAlchemy bağlantı adresi. PostgreSQL için: `postgresql+psycopg2://kullanici:sifre@host:5432/eco_profiler` |
| `LLM_PROVIDER`   | `ollama`                            | `ollama` veya `gemini` |
| `OLLAMA_URL`     | `http://localhost:11434`            | Ollama sunucusunun adresi |
| `OLLAMA_MODEL`   | `qwen2.5-coder:7b`                  | Ollama'da yüklü model adı |
| `GEMINI_API_KEY` | —                                   | Yalnızca `LLM_PROVIDER=gemini` iken gerekir |
| `GEMINI_MODEL`   | `gemini-2.5-flash`                  | Gemini model adı |
| `LLM_TIMEOUT`    | `300`                               | Tek bir LLM isteği için zaman aşımı (saniye) |

Backend `.env` dosyasını **kendiliğinden okumaz**. Yerel geliştirmede değişkenleri kabukta tanımlayın:

```bash
cp backend/.env.example backend/.env    # düzenleyin
set -a; source backend/.env; set +a
uvicorn app.main:app --reload
```

Docker Compose ile kullanırken değerleri kök dizindeki `.env` dosyasına yazabilirsiniz (ör. `OLLAMA_MODEL=...`, `POSTGRES_PASSWORD=...`). Compose bu dosyayı otomatik olarak okur.

### Model seçimi

Varsayılan model, kod için eğitilmiş `qwen2.5-coder:7b`'dir. Genel amaçlı `llama3:8b` ile karşılaştırma (Apple M1 Pro, 16 GB; her satır bir `/api/optimize` çağrısı, en fazla 2 deneme):

| Örnek            | llama3:8b | qwen2.5-coder:7b | Ölçülen hızlanma |
|------------------|-----------|------------------|------------------|
| `find_duplicates`| 0 / 5     | 6 / 6            | ~2000×           |
| `find_pair`      | 3 / 3     | 1 / 1            | ~600×            |
| `build_report`   | 3 / 3     | 1 / 1            | ~1,1×            |

`find_duplicates` sonuçları, en küçük karşı örnek geri bildirimi eklendikten sonraki ölçümlerdir; o olmadan qwen ilk denemede sıra hatası yapıyordu. Deneme sayıları küçüktür; bu tablo bir eğilim gösterir, garanti değildir. Model ilk denemede çoğu zaman hata yapar, ikinci deneme bu yüzden önemlidir. CPU'da tek bir istek 20–60 saniye sürer.

> **Gemini hakkında:** `LLM_PROVIDER=gemini` seçildiğinde **kaynak kod Google'ın sunucularına gönderilir**. Kapalı ağda veya gizli kodlarda yalnızca `ollama` kullanın.

---

## API uçları

Tüm uçlar `/api` altındadır. Etkileşimli belgeler için `/docs` adresine bakın.

| Yöntem | Yol             | Açıklama |
|--------|-----------------|----------|
| GET    | `/api/health`   | Veritabanı durumu, seçili LLM sağlayıcısı/modeli ve erişilebilirliği. Her iki bileşen de çalışıyorsa `status` alanı `"ok"`, değilse `"degraded"` olur; HTTP kodu her durumda 200'dür. |
| GET    | `/api/patterns` | Yeşil Kod Desenleri listesi |
| POST   | `/api/analyze`  | Yalnızca AST analizi; LLM kullanmaz, hızlıdır |
| POST   | `/api/optimize` | Analiz → LLM ile yeniden yazım → doğrulama → kayıt |
| GET    | `/api/history`  | Son 20 çalıştırma (en yeni önce) |

### `POST /api/analyze`

```json
// İstek
{ "code": "def total(values):\n    return sum(values)\n" }

// Yanıt
{
  "syntax_error": null,
  "functions": [
    { "name": "total", "line": 1, "complexity": "O(N)", "loop_depth": 1,
      "recursive_calls": 0, "memoized": false, "reason": "En derin döngü iç içeliği: 1." }
  ],
  "findings": []
}
```

Her bulgu şu alanları içerir: `line`, `pattern_code`, `title`, `detail` (Türkçe), `impact` (`"yüksek"`, `"orta"` veya `"düşük"`).

### `POST /api/optimize`

İstek gövdesi `/api/analyze` ile aynıdır. Yanıt:

```json
{
  "id": 12,
  "status": "optimized",                 // "clean" | "optimized" | "failed"
  "message": "Kod optimize edildi ve davranışın korunduğu doğrulandı.",
  "analysis":       { "...": "orijinal kodun analizi" },
  "analysis_after": { "...": "yeşil kodun analizi" },
  "green_code": "def find_duplicates(items):\n    ...",
  "changes": [ { "pattern": "YK-02", "explanation": "Üyelik kontrolü set ile yapıldı." } ],
  "verification": {
    "passed": true,
    "cases": [
      { "function": "find_duplicates", "input": "[[3, 1, 3, 2, 1]]",
        "old": "[3, 1]", "new": "[3, 1]", "equal": true, "old_ok": true },
      { "function": "find_duplicates", "input": "[[3, 3, 2, 1, 1]]",
        "derived": "azalan sıralı",
        "old": "[3, 1]", "new": "[3, 1]", "equal": true, "old_ok": true }
    ],
    "benchmark": {
      "old_seconds": 0.395, "new_seconds": 0.00018, "speedup": 2150.0,
      "functions": [ { "function": "find_duplicates", "old_seconds": 0.395,
                       "new_seconds": 0.00018, "outputs_equal": true,
                       "error": null, "auto": false } ]
    },
    "timed_out": false,
    "error": null
  },
  "notes": "",
  "warnings": [],
  "attempts": 1,
  "error": null
}
```

- `cases` öğelerindeki isteğe bağlı alanlar:
  - `derived`: sistemin türettiği girdi (`"azalan sıralı"`, `"ters"`, `"rastgele"`).
  - `invalid`: girdi imzaya uymuyor.
  - `note`: ek açıklama (ör. yan etki farkı).
  - `minimal`: uyuşmazlığın en küçük karşı örneği `{input, old, new}`.
- `benchmark.functions[].auto=true` ise ölçüm girdisi otomatik üretilmiştir.
- Bulgu yoksa LLM **hiç çağrılmaz** ve `status="clean"`, `message="Algoritmik enerji israfı tespit edilmedi"` döner.
- `status="failed"` durumunda, varsa son üretilen kod ve doğrulama ayrıntısı yine yanıtta yer alır. Arayüz üstte kırmızı "Doğrulanmış optimizasyon üretilemedi" kartını ve hata ayrıntısını gösterir; son üretilen kod incelenebilmesi için kod karşılaştırmasında yine görünür (kopyalanabilir). Bu kod kullanılmamalıdır.
- Sözdizimi hatalı kodda LLM çağrılmaz ve `status="failed"` döner. Hata, `error` alanında satır numarasıyla belirtilir.

---

## Sınırlar

- **Yalnızca Python.** Analiz Python'un `ast` modülüyle yapılır; başka diller desteklenmez. Doğrulayıcı yalnızca üst seviye fonksiyonları ve sınıf metotlarını karşılaştırır.
- **Karmaşıklık değerleri teoriktir.** `O(N²)` gibi değerler döngü iç içeliğine ve basit kurallara dayanan **tahminlerdir**:
  - Özyinelemeli ikili arama `O(log N)` yerine `O(N)` görünür.
  - Ağaç dolaşan çift özyineleme yanlışlıkla `O(2^N)` sayılabilir.
  - Kütüphane çağrılarının maliyeti bilinmez.
- **Desen tespiti sezgiseldir.** Yanlış pozitif ve yanlış negatif sonuçlar olabilir. Örneğin YK-02 yalnızca fonksiyon içinde liste olarak oluşturulan değişkenleri işaretler, parametreleri işaretlemez.
- **Ölçüm enerji değil, süredir.** Ölçüm tek bir benchmark girdisiyle (LLM'in ifadesi ya da otomatik üretilen girdi), sunucunun o anki yükünde yapılır. Girdi en kötü durumu temsil etmeyebilir; örneğin `find_pair` için çifti hemen bulan bir girdi hızlanmayı küçük gösterir. Sonuçlar donanıma bağlıdır ve bir eğilim gösterir.
- **Eşdeğerlik testi bir kanıt değildir.** Doğrulama yalnızca denenen girdilerde (LLM'in ≥4 girdisi, sistemin türettiği sıralı/ters/rastgele girdiler ve benchmark girdisi) aynı sonucu gösterir:
  - Girdiler yalnızca JSON değerlerinden oluşabilir. Rastgele girdi türetme yalnızca sayı ve string listeleri için yapılır; sözlük veya iç içe yapılar alan fonksiyonlar daha zayıf test edilir.
  - Türetilmiş girdiler fonksiyonun ön koşullarını bozabilir (ör. sıralı liste bekleyen bir fonksiyona ters liste verilmesi). Bu durumda orijinal kodla aynı davranmayan, ama gerçek kullanımda doğru olan bir optimizasyon reddedilebilir.
  - Rastgelelik, saat veya dış kaynak kullanan fonksiyonlar "farklı" görünebilir.
  - Kodu projeye almadan önce eşdeğerlik tablosunu inceleyin ve kendi testlerinizi çalıştırın.
- **Alt süreç tam bir güvenlik sanal ortamı (sandbox) DEĞİLDİR.** Kullanıcı kodu `python -I` ile ayrı bir süreçte, geçici bir dizinde, zaman aşımı ve kaynak sınırlarıyla çalıştırılır; gizli ortam değişkenleri aktarılmaz. Ancak:
  - Kod, backend'i çalıştıran kullanıcının yetkileriyle **dosya sistemine ve ağa erişebilir**.
  - Bellek sınırı (`RLIMIT_AS`) Linux'ta uygulanır, **macOS'ta uygulanmaz**. Windows'ta hiçbir kaynak sınırı uygulanmaz.
  - **Üretimde backend mutlaka container içinde çalıştırılmalıdır.** `docker-compose.yml` bunu salt okunur kök dosya sistemi, root olmayan kullanıcı, `cap_drop: ALL`, `no-new-privileges`, PID ve bellek sınırıyla yapar.
  - Daha güçlü yalıtım için gVisor / Kata Containers, ağsız ayrı bir yürütücü container veya ağ politikalarıyla dış erişimin kapatılması önerilir.
- **LLM çıktısı güvenilir değildir.** Model yanlış veya yarım kod üretebilir. Sistem bu kodu sözdizimi, fonksiyon imzası ve eşdeğerlik testiyle süzer ama tam doğruluğu garanti edemez.
- **Başarı oranı modele ve koda bağlıdır.** 7–8B'lik yerel modeller basit dönüşümlerde (döngüden çıkarma, `join`) güvenilirdir; sırayı koruma gibi ince anlam gerektiren dönüşümlerde ilk denemede sık hata yapar (bkz. [Model seçimi](#model-seçimi)). Başarısız sonuç, sistemin yanlış kodu reddettiği anlamına gelir; orijinal kod kullanılmaya devam edilmelidir.
- **Kimlik doğrulama yoktur.** Panel, güvenilir bir iç ağda kullanılmak üzere tasarlanmıştır. Dışarıya açılacaksa önüne kimlik doğrulama yapan bir ters vekil (reverse proxy) konulmalıdır.
