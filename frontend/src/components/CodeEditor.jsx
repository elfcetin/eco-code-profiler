import { useEffect, useRef } from 'react'

const LINE_HEIGHT = 21 // styles.css içindeki --code-line ile aynı olmalı

/**
 * Satır numaralı, satır vurgulamalı kod giriş alanı.
 * highlights: Map<satır, 'high' | 'medium' | 'low' | 'error'>
 * focus: { line, nonce } — değiştiğinde ilgili satıra kaydırır.
 */
export default function CodeEditor({ value, onChange, highlights, focus, disabled }) {
  const textareaRef = useRef(null)
  const gutterRef = useRef(null)
  const layerRef = useRef(null)
  const lineCount = value.split('\n').length

  function syncScroll() {
    const ta = textareaRef.current
    gutterRef.current.style.transform = `translateY(${-ta.scrollTop}px)`
    layerRef.current.style.transform = `translateY(${-ta.scrollTop}px)`
  }

  function handleKeyDown(e) {
    if (e.key !== 'Tab' || e.shiftKey) return
    e.preventDefault()
    const ta = e.currentTarget
    ta.setRangeText('    ', ta.selectionStart, ta.selectionEnd, 'end')
    onChange(ta.value)
  }

  useEffect(() => {
    if (!focus) return
    const ta = textareaRef.current
    ta.scrollTop = Math.max(0, (focus.line - 1) * LINE_HEIGHT - 3 * LINE_HEIGHT)
    const lines = ta.value.split('\n')
    const start = lines.slice(0, focus.line - 1).reduce((n, l) => n + l.length + 1, 0)
    ta.focus()
    ta.setSelectionRange(start, start + (lines[focus.line - 1] ?? '').length)
    syncScroll()
  }, [focus])

  const rows = Array.from({ length: lineCount }, (_, i) => highlights?.get(i + 1))

  return (
    <div className="editor">
      <div className="editor-gutter" aria-hidden="true">
        <div ref={gutterRef}>
          {rows.map((hl, i) => (
            <div key={i} className={`gutter-line ${hl ? `hl-${hl}` : ''}`}>
              {i + 1}
            </div>
          ))}
        </div>
      </div>
      <div className="editor-body">
        <div className="editor-layer" ref={layerRef} aria-hidden="true">
          {rows.map((hl, i) => (
            <div key={i} className={`layer-line ${hl ? `hl-${hl}` : ''}`} />
          ))}
        </div>
        <textarea
          ref={textareaRef}
          className="editor-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onScroll={syncScroll}
          onKeyDown={handleKeyDown}
          spellCheck={false}
          autoCapitalize="off"
          autoComplete="off"
          wrap="off"
          disabled={disabled}
          aria-label="Python kodu"
          placeholder="Python kodunuzu buraya yapıştırın…"
        />
      </div>
    </div>
  )
}
