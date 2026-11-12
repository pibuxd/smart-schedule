import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
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

const phoneSchema = z.object({
  phone: z
    .string()
    .transform((value) => value.replace(/[\s-]/g, '').replace(/^(\+48|0048)/, ''))
    .refine((value) => /^\d{9}$/.test(value), 'Wpisz 9 cyfr numeru, na przykład 512 345 678.'),
})
type PhoneForm = z.input<typeof phoneSchema>

export function LoginScreen() {
  const [sent, setSent] = useState<RequestCodeOut | null>(null)

  return (
    <main className="mx-auto flex min-h-dvh max-w-(--column) flex-col gap-6 px-4 pt-6 pb-8">
      <Wordmark />
      {sent ? (
        <CodeStep sent={sent} onResent={setSent} onChangePhone={() => setSent(null)} />
      ) : (
        <PhoneStep onSent={setSent} />
      )}
    </main>
  )
}

function PhoneStep({ onSent }: { onSent: (sent: RequestCodeOut) => void }) {
  const requestCode = useRequestCode()
  const form = useForm<PhoneForm, unknown, z.output<typeof phoneSchema>>({
    resolver: zodResolver(phoneSchema),
    defaultValues: { phone: '' },
  })
  const fieldError = form.formState.errors.phone?.message

  const submit = form.handleSubmit(({ phone }) => {
    requestCode.mutate(
      { data: { phone: `+48${phone}`, purpose: 'login' } },
      { onSuccess: (response) => onSent(response.data as RequestCodeOut) },
    )
  })

  return (
    <form className="mt-6 flex flex-1 flex-col gap-5" onSubmit={submit} noValidate>
      <div className="grid gap-2">
        <h1 className="m-0 text-2xl font-extrabold">Zaloguj się</h1>
        <p className="m-0 text-ink-muted">Wpisz swój numer telefonu. Wyślemy na niego SMS z kodem.</p>
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
      <div className="mt-auto">
        <Button type="submit" wide disabled={requestCode.isPending}>
          {requestCode.isPending ? 'Wysyłam kod…' : 'Wyślij kod SMS'}
        </Button>
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
  onResent,
  onChangePhone,
}: {
  sent: RequestCodeOut
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
    if (value.length === 6 && !verify.isPending) {
      verify.mutate(
        { data: { phone: sent.phone, code: value } },
        {
          onSuccess: async () => {
            await queryClient.invalidateQueries({ queryKey: getMeQueryKey() })
            await navigate({ to: '/' })
          },
          onError: () => setCode(''),
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
          ważny {Math.round(sent.expires_in_s / 60)} minut.
        </p>
      </div>
      <CodeInput value={code} onChange={check} disabled={verify.isPending} invalid={verify.isError && !code} />
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
        <Button
          variant="secondary"
          wide
          disabled={left > 0 || resend.isPending}
          onClick={() =>
            resend.mutate(
              { data: { phone: sent.phone, purpose: 'login' } },
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
          {left > 0 ? `Wyślij kod jeszcze raz za ${minutes}:${seconds}` : 'Wyślij kod jeszcze raz'}
        </Button>
        <Button variant="quiet" size="normal" wide onClick={onChangePhone}>
          Zmień numer telefonu
        </Button>
      </div>
    </div>
  )
}
