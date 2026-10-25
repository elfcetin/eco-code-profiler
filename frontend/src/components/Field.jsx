import { cloneElement, useId } from 'react'

/** Etiket alana id ile bağlanır; etiketin içine konmaz (aksi halde erişilebilir ad alanın
 *  içeriğini de kapsar: "Sonra" yerine "Sonra from collections import ..."). */
export default function Field({ label, inline = false, children }) {
  const id = useId()
  return (
    <div className={inline ? 'field field-inline' : 'field'}>
      <label htmlFor={id}>{label}</label>
      {cloneElement(children, { id })}
    </div>
  )
}
