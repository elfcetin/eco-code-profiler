import { useMemo, useState } from 'react'
import { diffLines } from 'diff'

function splitLines(value) {
  const lines = value.split('\n')
  if (lines[lines.length - 1] === '') lines.pop()
  return lines
}

const withNewline = (s) => (s.endsWith('\n') ? s : `${s}\n`)

/** diffLines çıktısını yan yana satır çiftlerine çevirir. */
function buildRows(oldCode, newCode) {
  const parts = diffLines(withNewline(oldCode), withNewline(newCode))
  const rows = []
  let left = 1
  let right = 1
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]
    if (part.removed && parts[i + 1]?.added) {
      const removed = splitLines(part.value)
      const added = splitLines(parts[i + 1].value)
      for (let k = 0; k < Math.max(removed.length, added.length); k++) {
        rows.push({
          left: k < removed.length ? { n: left++, text: removed[k], type: 'del' } : null,
          right: k < added.length ? { n: right++, text: added[k], type: 'add' } : null,
        })
      }
      i++
    } else if (part.removed) {
      for (const text of splitLines(part.value)) rows.push({ left: { n: left++, text, type: 'del' }, right: null })
    } else if (part.added) {
      for (const text of splitLines(part.value)) rows.push({ left: null, right: { n: right++, text, type: 'add' } })
    } else {
      for (const text of splitLines(part.value)) {
        rows.push({ left: { n: left++, text, type: 'same' }, right: { n: right++, text, type: 'same' } })
      }
    }
  }
  return rows
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
}

function Pane({ title, cells }) {
  return (
    <div className="diff-pane">
      <div className="diff-pane-title">{title}</div>
      <div className="diff-scroll">
        <div className="diff-lines">
          {cells.map((cell, i) => (
            <div key={i} className={`diff-line ${cell ? `diff-${cell.type}` : 'diff-empty'}`}>
              <span className="diff-num">{cell?.n ?? ''}</span>
              <span className="diff-sign">{cell?.type === 'add' ? '+' : cell?.type === 'del' ? '−' : ''}</span>
              <span className="diff-text">{cell?.text ?? ''}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function DiffView({ oldCode, newCode }) {
  const rows = useMemo(() => buildRows(oldCode, newCode), [oldCode, newCode])
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    await copyText(newCode)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <section className="card">
      <div className="card-header">
        <h3>Kod karşılaştırması</h3>
        <button type="button" className="btn btn-secondary" onClick={handleCopy}>
          {copied ? 'Kopyalandı ✓' : 'Yeşil Kodu Kopyala'}
        </button>
      </div>
      <div className="diff">
        <Pane title="Eski kod" cells={rows.map((r) => r.left)} />
        <Pane title="Yeşil Kod" cells={rows.map((r) => r.right)} />
      </div>
    </section>
  )
}
