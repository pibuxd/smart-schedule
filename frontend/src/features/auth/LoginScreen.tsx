import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { getMeQueryKey, useRequestCode, useVerifyCode } from '../../api/generated/auth/auth'
import type { RequestCodeOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { InlineError } from '../../components/ui/status'
import { Wordmark } from '../../components/Wordmark'
import { CodeInput } from './CodeInput'
import { prettyPhone } from './phone'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { takeSessionEnded } from '../../lib/session-ended'

const phoneSchema = z.object({
  phone: z
    .string()
    .transform((value) => value.replace(/[\s-]/g, '').replace(/^(\+48|0048)/, ''))
    .refine((value) => /^\d{9}$/.test(value), 'Wpisz 9 cyfr numeru, na przykład 512 345 678.'),
})
type PhoneForm = z.input<typeof phoneSchema>

type Purpose = 'login' | 'register'

const SENT_KEY = 'grafikomat.code-sent'
/**
 * The code step survives a page refresh (someone switches to their SMS app and back, the browser reloads):
 * the number and the times are kept in this tab until the code expires.
 */
function readSent(purpose: Purpose): RequestCodeOut | null {
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(SENT_KEY) ?? 'null') as
      | { sent: RequestCodeOut; at: number; purpose: Purpose }
      | null
    if (!saved || saved.purpose !== purpose) return null
    const passed = Math.floor((Date.now() - saved.at) / 1000)
    if (passed < 0 || passed >= saved.sent.expires_in_s) return null
    return {
      ...saved.sent,
      expires_in_s: saved.sent.expires_in_s - passed,
      resend_after_s: Math.max(0, saved.sent.resend_after_s - passed),
    }
  } catch {
    return null
  }
}

function storeSent(sent: RequestCodeOut | null, purpose: Purpose) {
  try {
    if (sent) window.sessionStorage.setItem(SENT_KEY, JSON.stringify({ sent, at: Date.now(), purpose }))
    else window.sessionStorage.removeItem(SENT_KEY)
  } catch {
    // Blocked storage: a refresh goes back to the phone number, as before.
  }
}

/** Logging in, or (purpose "register") the first step of registering a new company: the phone number and the code. */
export function LoginScreen({ purpose = 'login' }: { purpose?: Purpose }) {
  const [sent, setSentState] = useState<RequestCodeOut | null>(() => readSent(purpose))
  const setSent = (value: RequestCodeOut | null) => {
    storeSent(value, purpose)
    setSentState(value)
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-(--column) flex-col gap-6 px-4 pt-6 pb-8">
      <Wordmark />
      {sent ? (
        <CodeStep sent={sent} purpose={purpose} onResent={setSent} onChangePhone={() => setSent(null)} />
      ) : (
        <PhoneStep purpose={purpose} onSent={setSent} />
      )}
    </main>
  )
}

function PhoneStep({ purpose, onSent }: { purpose: Purpose; onSent: (sent: RequestCodeOut) => void }) {
  const requestCode = useRequestCode()
  const [sessionEnded] = useState(takeSessionEnded)
  const form = useForm<PhoneForm, unknown, z.output<typeof phoneSchema>>({
    resolver: zodResolver(phoneSchema),
    defaultValues: { phone: '' },
  })
  const fieldError = form.formState.errors.phone?.message

  const submit = form.handleSubmit(({ phone }) => {
    requestCode.mutate(
      { data: { phone: `+48${phone}`, purpose } },
      { onSuccess: (response) => onSent(response.data as RequestCodeOut) },
    )
  })

  return (
    <form className="mt-6 flex flex-1 flex-col gap-5" onSubmit={submit} noValidate>
      <div className="grid gap-2">
        <h1 className="m-0 text-2xl font-extrabold">{purpose === 'register' ? 'Załóż firmę' : 'Zaloguj się'}</h1>
        <p className="m-0 text-ink-muted">
          {purpose === 'register'
            ? 'Wpisz swój numer telefonu. Wyślemy Ci SMS z kodem. Potem podasz nazwę firmy, a pracowników zaprosisz później.'
            : 'Wpisz swój numer telefonu. Wyślemy Ci SMS z kodem.'}
        </p>
        {sessionEnded && (
          <p role="status" className="m-0 rounded-md bg-accent-soft px-3 py-2 font-semibold">
            Sesja wygasła. Zaloguj się jeszcze raz. To, co już zapisane, zostało.
          </p>
        )}
      </div>
      <div className="grid gap-2">
        <label htmlFor="phone" className="font-semibold">
          Numer telefonu
        </label>
        <div className="flex min-h-(--touch-main) overflow-hidden rounded-md border-2 border-ink bg-surface focus-within:border-accent focus-within:ring-3 focus-within:ring-accent-soft">
          <span className="flex items-center bg-grid px-3.5 font-semibold" aria-hidden="true">
            +48
          </span>
          <input
            id="phone"
            className="min-w-0 flex-1 bg-transparent px-3.5 text-lg tracking-wide outline-none"
            type="tel"
            inputMode="tel"
            autoComplete="tel-national"
            placeholder="512 345 678"
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={fieldError ? 'phone-error' : undefined}
            {...form.register('phone')}
          />
        </div>
        {fieldError && (
          <p id="phone-error" className="m-0 text-sm text-cannot">
            {fieldError}
          </p>
        )}
      </div>
      {requestCode.isError && <InlineError>{errorMessage(requestCode.error, NETWORK_PROBLEM)}</InlineError>}
      <div className="mt-auto grid gap-2">
        <Button type="submit" wide disabled={requestCode.isPending}>
          {requestCode.isPending ? 'Wysyłam kod…' : 'Wyślij kod SMS'}
        </Button>
        {purpose === 'register' ? (
          <Link to="/logowanie" className="inline-flex min-h-(--touch) items-center justify-center font-semibold text-accent underline underline-offset-4">
            Masz już konto? Zaloguj się
          </Link>
        ) : (
          <Link to="/rejestracja" className="inline-flex min-h-(--touch) items-center justify-center font-semibold text-accent underline underline-offset-4">
            Prowadzisz lokal? Załóż firmę
          </Link>
        )}
      </div>
    </form>
  )
}

function useCountdown(seconds: number, restartKey: unknown) {
  const [left, setLeft] = useState(seconds)
  useEffect(() => {
    setLeft(seconds)
    const timer = window.setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000)
    return () => window.clearInterval(timer)
  }, [seconds, restartKey])
  return left
}

function CodeStep({
  sent,
  purpose,
  onResent,
  onChangePhone,
}: {
  sent: RequestCodeOut
  purpose: Purpose
  onResent: (sent: RequestCodeOut) => void
  onChangePhone: () => void
}) {
  const [code, setCode] = useState('')
  const verify = useVerifyCode()
  const resend = useRequestCode()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const left = useCountdown(sent.resend_after_s, sent)

  const check = (value: string) => {
    setCode(value)
    // A new digit starts a new try: the old "wrong code" message would only confuse.
    if (verify.isError) verify.reset()
    if (value.length === 6 && !verify.isPending) {
      verify.mutate(
        { data: { phone: sent.phone, code: value } },
        {
          onSuccess: async () => {
            storeSent(null, purpose)
            await queryClient.invalidateQueries({ queryKey: getMeQueryKey() })
            await navigate({ to: purpose === 'register' ? '/rejestracja' : '/' })
          },
        },
      )
    }
  }

  const minutes = Math.floor(left / 60)
  const seconds = String(left % 60).padStart(2, '0')

  return (
    <div className="mt-6 flex flex-1 flex-col gap-5">
      <div className="grid gap-2">
        <h1 className="m-0 text-2xl font-extrabold">Wpisz kod z SMS-a</h1>
        <p className="m-0 text-ink-muted">
          Wysłaliśmy go na numer <b className="whitespace-nowrap text-ink">{prettyPhone(sent.phone)}</b>. Kod jest
          ważny {Math.max(1, Math.round(sent.expires_in_s / 60))} min.
        </p>
      </div>
      <CodeInput value={code} onChange={check} disabled={verify.isPending} invalid={verify.isError} />
      {verify.isPending ? (
        <p role="status" className="m-0 text-ink-muted">
          Sprawdzam kod…
        </p>
      ) : verify.isError ? (
        <InlineError>{errorMessage(verify.error, NETWORK_PROBLEM)}</InlineError>
      ) : (
        <p className="m-0 text-sm text-ink-muted">Po wpisaniu szóstej cyfry zalogujemy Cię od razu.</p>
      )}
      {resend.isError && <InlineError>{errorMessage(resend.error, NETWORK_PROBLEM)}</InlineError>}
      <div className="mt-auto grid gap-1">
        {left > 0 && (
          <p className="m-0 text-center font-semibold" role="timer">
            Nowy kod możesz dostać za {minutes}:{seconds}.
          </p>
        )}
        {left === 0 && (
        <Button
          variant="secondary"
          wide
          disabled={resend.isPending}
          onClick={() =>
            resend.mutate(
              { data: { phone: sent.phone, purpose } },
              {
                onSuccess: (response) => {
                  setCode('')
                  verify.reset()
                  onResent(response.data as RequestCodeOut)
                },
              },
            )
          }
        >
          Wyślij kod jeszcze raz
        </Button>
        )}
        <Button variant="quiet" size="normal" wide onClick={onChangePhone}>
          Zmień numer telefonu
        </Button>
      </div>
    </div>
  )
}
