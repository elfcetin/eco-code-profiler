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

IS_SQLITE: bool = DATABASE_URL.startswith("sqlite")
