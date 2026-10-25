"""Uygulama ayarları: ortam değişkenlerinden okunur."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Veritabanı: DATABASE_URL verilmezse geliştirme için yerel SQLite kullanılır.
DATABASE_URL: str = os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'eco_profiler.db'}"

# LLM sağlayıcısı: "ollama" (yerel, varsayılan) veya "gemini".
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
if LLM_PROVIDER not in ("ollama", "gemini"):
    raise ValueError(f"Geçersiz LLM_PROVIDER: {LLM_PROVIDER!r} (ollama|gemini olmalı)")

# Ollama
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")

# Gemini (isteğe bağlı)
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY") or None
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Tek bir LLM isteği için zaman aşımı (saniye); CPU üzerinde yerel modeller yavaş olabilir.
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "300"))

# Tahmini enerji hesabı varsayımları (ölçüm DEĞİL; bkz. energy.py).
# İşlemcinin çalışırken çektiği güç (W) ve optimize edilen fonksiyonun günde kaç kez çalıştığı.
CPU_POWER_WATTS: float = float(os.getenv("CPU_POWER_WATTS", "65"))
RUNS_PER_DAY: float = float(os.getenv("RUNS_PER_DAY", "10000"))
if CPU_POWER_WATTS <= 0 or RUNS_PER_DAY <= 0:
    raise ValueError("CPU_POWER_WATTS ve RUNS_PER_DAY pozitif olmalı")

# Yönetici şifresi: desen düzenleme uçları için. Kodda sabit şifre YOK; tanımlı değilse düzenleme kapalıdır.
ADMIN_PASSWORD: str | None = os.getenv("ADMIN_PASSWORD") or None
# Yönetici oturumunun (token) geçerlilik süresi (saat).
ADMIN_TOKEN_HOURS: float = float(os.getenv("ADMIN_TOKEN_HOURS", "8"))

IS_SQLITE: bool = DATABASE_URL.startswith("sqlite")
