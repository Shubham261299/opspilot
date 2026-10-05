import { FileSpreadsheet, LoaderCircle } from 'lucide-react'
import { type DragEvent, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

interface FileDropZoneProps {
  label: string // e.g. "Drop customers.xlsx here"
  hint: string // e.g. "or click to choose · Excel .xlsx, up to 5 MB"
  accept: string // for the file picker, e.g. ".xlsx"
  busyLabel: string | null // shown with a spinner while a file is being sent
  onFile: (file: File) => void
}

/** A box you can drop a file on, click, or focus and press Enter, to choose a file. */
export function FileDropZone({ label, hint, accept, busyLabel, onFile }: FileDropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function openFilePicker() {
    inputRef.current?.click()
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault() // stop the browser from opening the file itself
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) onFile(file)
  }

  function onDragLeave(event: DragEvent<HTMLDivElement>) {
    // Moving over a child element also fires "dragleave"; react only when really leaving.
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-busy={busyLabel !== null}
      onClick={openFilePicker}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          openFilePicker()
        }
      }}
      onDragOver={(event) => {
        event.preventDefault() // required, or the browser won't allow dropping here
        setDragging(true)
      }}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={cn(
        'flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed bg-background px-4 py-8 text-center transition-colors',
        dragging ? 'border-primary bg-primary/5' : 'border-border hover:border-muted-foreground/40',
      )}
    >
      {busyLabel ? (
        <LoaderCircle className="size-7 animate-spin text-muted-foreground" aria-hidden />
      ) : (
        <FileSpreadsheet className="size-7 text-muted-foreground" aria-hidden />
      )}
      <p className="text-sm font-medium">{busyLabel ?? label}</p>
      <p className="text-xs text-muted-foreground">{hint}</p>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onClick={(event) => event.stopPropagation()} // don't bubble back to the drop zone
        onChange={(event) => {
          const file = event.target.files?.[0]
          event.target.value = '' // so choosing the same file again still triggers onChange
          if (file) onFile(file)
        }}
      />
    </div>
  )
}
