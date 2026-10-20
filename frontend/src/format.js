const nf = (digits) => new Intl.NumberFormat('tr-TR', { maximumFractionDigits: digits, minimumFractionDigits: digits })

export function formatSeconds(s) {
  if (s == null) return '—'
  if (s < 1e-3) return `${nf(0).format(s * 1e6)} µs`
  if (s < 1) return `${nf(1).format(s * 1e3)} ms`
  return `${nf(2).format(s)} sn`
}

export function formatSpeedup(x) {
  if (x == null) return '—'
  return `${nf(x >= 10 ? 0 : 1).format(x)}×`
}

export function formatDate(iso) {
  return new Date(iso).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' })
}

export const IMPACT_CLASS = { yüksek: 'high', orta: 'medium', düşük: 'low' }
export const IMPACT_RANK = { yüksek: 3, orta: 2, düşük: 1 }
