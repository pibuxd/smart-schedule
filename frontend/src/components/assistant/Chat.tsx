import { ArrowUp, MessageCircle } from 'lucide-react'
import { useEffect, useRef, type ReactNode, type RefObject } from 'react'

import { cn } from '../../lib/cn'

export function AssistantMark({ large = false }: { large?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-md bg-accent text-accent-ink',
        large ? 'h-14 w-14' : 'h-8 w-8',
      )}
    >
      <MessageCircle size={large ? 28 : 18} strokeWidth={1.8} />
    </span>
  )
}

export function ChatMessage({
  from,
  children,
  date,
  label,
}: {
  from: 'user' | 'assistant'
  children: ReactNode
  date?: string
  label?: string
}) {
  const mine = from === 'user'
  return (
    <div className={cn('flex min-w-0 gap-3', mine && 'justify-end')}>
      {!mine && <AssistantMark />}
      <div className={cn('min-w-0', mine ? 'max-w-[88%] sm:max-w-[80%]' : 'w-full max-w-[44rem]')}>
        <div className={cn('mb-1.5 flex items-center gap-2 text-xs text-ink-muted', mine && 'justify-end')}>
          <span className="font-semibold">{label ?? (mine ? 'Ty' : 'Asystent')}</span>
          {date && (
            <time dateTime={date}>
              {new Date(date).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })}
            </time>
          )}
        </div>
        <div
          className={cn(
            'min-w-0 leading-relaxed [overflow-wrap:anywhere]',
            mine ? 'rounded-lg rounded-tr-sm bg-accent-soft px-4 py-3 text-ink' : 'grid gap-3 pt-0.5',
          )}
        >
          {children}
        </div>
      </div>
    </div>
  )
}

/** A small robot reading a book: its eyes run along a line and jump back (still with reduced motion). */
export function ReadingRobot() {
  return (
    <svg
      aria-hidden="true"
      data-testid="reading-robot"
      viewBox="0 0 24 24"
      width="28"
      height="28"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0 text-accent"
    >
      <g className="robot-head">
        <path d="M12 2.8v2.2" />
        <rect x="5" y="5" width="14" height="10" rx="3" />
        <g className="robot-eyes" fill="currentColor" stroke="none">
          <circle cx="9.5" cy="9.5" r="1.2" />
          <circle cx="14.5" cy="9.5" r="1.2" />
        </g>
        <path d="M10 12.5h4" />
      </g>
      <path d="M4 18.5c2.7-1.3 5.3-1.3 8 0 2.7-1.3 5.3-1.3 8 0v3.5c-2.7-1.3-5.3-1.3-8 0-2.7-1.3-5.3-1.3-8 0z" />
      <path d="M12 18.5V22" />
    </svg>
  )
}

export function ChatTyping({ children = 'Przygotowuję odpowiedź…' }: { children?: ReactNode }) {
  return (
    <p role="status" className="m-0 flex items-center gap-2 py-1 text-sm text-ink-muted">
      <ReadingRobot />
      {children}
    </p>
  )
}

export function ChatComposer({
  text,
  onChange,
  onSend,
  disabled,
  waiting,
  sending,
  inputRef,
  label = 'Twoja wiadomość',
  placeholder = 'Napisz wiadomość…',
  sendLabel = 'Wyślij wiadomość',
  enterSends = true,
  footer,
}: {
  text: string
  onChange: (text: string) => void
  onSend: () => void
  disabled?: boolean
  waiting?: boolean
  sending?: boolean
  inputRef?: RefObject<HTMLTextAreaElement | null>
  label?: string
  placeholder?: string
  sendLabel?: string
  enterSends?: boolean
  footer?: ReactNode
}) {
  const ownRef = useRef<HTMLTextAreaElement>(null)
  const ref = inputRef ?? ownRef
  const canSend = !!text.trim() && !disabled && !sending && !waiting
  useEffect(() => {
    const field = ref.current
    if (field) {
      field.style.height = 'auto'
      field.style.height = `${Math.min(field.scrollHeight, 160)}px`
    }
  }, [text, ref])
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (canSend) onSend()
      }}
      className="grid gap-2"
    >
      <div
        className={cn(
          'flex items-end gap-2 rounded-lg border border-line bg-surface p-2 transition-colors focus-within:border-accent focus-within:ring-2 focus-within:ring-accent-soft',
          !enterSends && 'flex-col',
        )}
      >
        <textarea
          ref={ref}
          rows={1}
          aria-label={label}
          placeholder={placeholder}
          value={text}
          maxLength={1000}
          disabled={disabled || sending}
          enterKeyHint={enterSends ? 'send' : 'enter'}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (enterSends && event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              if (canSend) onSend()
            }
          }}
          className="max-h-40 min-h-(--touch) w-full resize-none border-0 bg-transparent px-3 py-2.5 text-base leading-relaxed text-ink outline-none placeholder:text-ink-muted focus-visible:outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          aria-label={sending ? 'Wysyłam…' : sendLabel}
          disabled={!canSend}
          className={cn(
            'flex h-(--touch) shrink-0 cursor-pointer items-center justify-center gap-2 bg-accent text-accent-ink transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-paper disabled:text-ink-muted',
            enterSends ? 'w-(--touch) rounded-full' : 'rounded-md px-4 text-sm font-semibold',
          )}
        >
          {!enterSends && <span>{sendLabel}</span>}
          <ArrowUp size={enterSends ? 24 : 18} aria-hidden="true" />
        </button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-1 text-xs text-ink-muted">
        <span>
          {sending
            ? 'Wysyłam…'
            : waiting
              ? 'Możesz pisać. Wyślesz kolejną wiadomość po otrzymaniu odpowiedzi.'
              : footer}
        </span>
        {text.length > 800 ? (
          <span>{text.length}/1000</span>
        ) : (
          enterSends && <span className="hidden sm:inline">Enter — wyślij · Shift+Enter — nowy wiersz</span>
        )}
      </div>
    </form>
  )
}
