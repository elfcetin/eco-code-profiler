const nf = (digits) => new Intl.NumberFormat('tr-TR', { maximumFractionDigits: digits, minimumFractionDigits: digits })

export function formatSeconds(s) {
  if (s == null) return '—'
  // 1 µs altı "0 µs" görünmesin: nanosaniye; 1 ns altı (ör. 0) "<1 ns".
  if (s < 1e-6) return s * 1e9 < 1 ? '<1 ns' : `${nf(0).format(s * 1e9)} ns`
  if (s < 1e-3) return `${nf(s < 1e-5 ? 1 : 0).format(s * 1e6)} µs`
  if (s < 1) return `${nf(1).format(s * 1e3)} ms`
  return `${nf(2).format(s)} sn`
}

export function formatSpeedup(x) {
  if (x == null) return '—'
  return `${nf(x >= 10 ? 0 : 1).format(x)}×`
}

/** Tahmini değerler için 3 anlamlı basamak (ör. 26,4 · 0,00047). */
export function formatEstimate(x) {
  if (x == null) return '—'
  return new Intl.NumberFormat('tr-TR', { maximumSignificantDigits: 3 }).format(x)
}

export function formatCount(x) {
  return new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 1 }).format(x)
}

/** Enerji tahmininin varsayım notu (Ölçülen süre kartı ve Rapor sekmesi aynı metni kullanır). */
export function energyAssumptionNote(watts, runsPerDay, subject = 'fonksiyon') {
  return (
    `Varsayım: işlemci ${formatCount(watts)} W, ${subject} günde ${formatCount(runsPerDay)} kez çalışıyor. ` +
    'Gerçek tüketim donanıma ve kullanıma bağlıdır.'
  )
}

export function formatPercent(x) {
  if (x == null) return '—'
  return new Intl.NumberFormat('tr-TR', { style: 'percent', maximumFractionDigits: 0 }).format(x)
}

const HAS_ZONE = /(Z|[+-]\d{2}:?\d{2})$/i

/** API tarihini Date'e çevirir. Saat dilimi yoksa UTC kabul edilir (API zamanları UTC'dir);
 *  aksi halde tarayıcı etiketsiz ISO metnini yerel saat sanar. */
export function parseApiDate(iso) {
  if (iso == null) return null
  return new Date(HAS_ZONE.test(iso) ? iso : `${iso}Z`)
}

/** Tarayıcının yerel saat diliminde gösterir. */
export function formatDate(iso, timeZone) {
  const date = parseApiDate(iso)
  if (!date || Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short', timeZone })
}

export const IMPACT_CLASS = { yüksek: 'high', orta: 'medium', düşük: 'low' }
export const IMPACT_RANK = { yüksek: 3, orta: 2, düşük: 1 }
