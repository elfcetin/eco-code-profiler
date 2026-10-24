"""Ölçülen süre farkından TAHMİNİ enerji etkisi.

Bu bir ölçüm değildir. Sistem enerjiyi ölçmez; yalnızca çalışma süresini ölçer. Buradaki
değerler iki varsayıma dayanır: işlemcinin çektiği güç (CPU_POWER_WATTS) ve fonksiyonun
günde kaç kez çalıştığı (RUNS_PER_DAY). Gerçek tüketim donanıma ve kullanıma bağlıdır.

    tek çalıştırma başına tasarruf (J)   = (eski_süre - yeni_süre) × güç (W)
    yıllık tahmini tasarruf (kWh)        = J × günlük çalıştırma × 365 / 3.600.000
"""

from __future__ import annotations

from . import config

JOULES_PER_KWH = 3_600_000
DAYS_PER_YEAR = 365


def estimate(
    old_seconds: float | None,
    new_seconds: float | None,
    watts: float | None = None,
    runs_per_day: float | None = None,
) -> dict | None:
    """Tahmini enerji tasarrufu; süre ölçülmediyse veya yeni kod daha hızlı değilse None.

    watts / runs_per_day verilmezse config'deki varsayılanlar kullanılır.
    """
    watts = config.CPU_POWER_WATTS if watts is None else watts
    runs_per_day = config.RUNS_PER_DAY if runs_per_day is None else runs_per_day
    if watts <= 0 or runs_per_day <= 0:
        raise ValueError("Güç ve günlük çalıştırma sayısı pozitif olmalı.")
    if old_seconds is None or new_seconds is None:
        return None
    saved_seconds = old_seconds - new_seconds
    if saved_seconds <= 0:  # yeni kod daha yavaş (veya aynı): tasarruf tahmini yok
        return None

    joules_per_run = saved_seconds * watts
    return {
        "joules_per_run": joules_per_run,
        "kwh_per_year": joules_per_run * runs_per_day * DAYS_PER_YEAR / JOULES_PER_KWH,
        "watts": watts,
        "runs_per_day": runs_per_day,
    }
