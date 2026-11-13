import { useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { useState } from 'react'

import { useRedeemSubscriptionCode, useSubscription } from '../../api/generated/billing/billing'
import type { SubscriptionOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { Tag, TextField } from '../../components/ui/field'
import { ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { dayAndMonth } from '../../lib/dates'
import { useManager } from './ManagerContext'
import { statusWords } from './words'

/** "Dostęp": how long the company can use Grafikomat, how many arrangements are left, and entering a code. */
export function AccessScreen() {
  const { companyId } = useManager()
  const subscription = useSubscription(companyId)
  if (subscription.isPending) return <Loading>Sprawdzam dostęp…</Loading>
  if (subscription.isError) {
    return (
      <ErrorState onRetry={() => void subscription.refetch()}>
        {errorMessage(subscription.error, 'Nie udało się sprawdzić dostępu. Spróbuj jeszcze raz.')}
      </ErrorState>
    )
  }
  const data = subscription.data.data as SubscriptionOut
  return (
    <div className="grid max-w-[720px] gap-6">
      <h1 className="m-0 text-2xl font-extrabold">Dostęp do Grafikomatu</h1>
      <section className="grid gap-2 rounded-md border border-line bg-surface p-4">
        <span>
          <Tag tone={data.read_only ? 'bad' : data.expiring_soon ? 'warn' : 'accent'}>{statusWords(data)}</Tag>
        </span>
        <p className="m-0">{explanation(data)}</p>
        <p className="m-0 text-ink-muted">
          Ułożenia grafiku w tym miesiącu: {data.generations_used} z {data.generations_limit}.
        </p>
      </section>
      <RedeemForm companyId={companyId} />
    </div>
  )
}

function explanation(data: SubscriptionOut): string {
  const until = data.ends_at ? dayAndMonth(new Date(data.ends_at)) : ''
  if (data.read_only && !data.ends_at) {
    return 'Ta firma nie ma jeszcze kodu dostępu, więc niczego nie można zmieniać. Wpisz kod poniżej.'
  }
  if (data.read_only && data.trial) {
    return `Okres próbny skończył się ${until}. Dane są bezpieczne i można je oglądać; żeby znów układać grafiki, wpisz kod.`
  }
  if (data.read_only) {
    return `Dostęp skończył się ${until}. Dane są bezpieczne i można je oglądać; żeby znów układać grafiki, wpisz nowy kod.`
  }
  if (data.trial) {
    return `Możesz używać wszystkiego do ${until}. Potem dane zostaną, ale do zmian potrzebny będzie kod dostępu.`
  }
  return `Dostęp trwa do ${until}. Kolejny kod przedłuży go od tej daty, więc nic nie przepadnie.`
}

function RedeemForm({ companyId }: { companyId: string }) {
  const redeem = useRedeemSubscriptionCode()
  const queryClient = useQueryClient()
  const [code, setCode] = useState('')
  const [done, setDone] = useState<string | null>(null)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    setDone(null)
    redeem.mutate(
      { companyId, data: { code } },
      {
        onSuccess: (response) => {
          const data = response.data as SubscriptionOut
          setCode('')
          setDone(`Kod przyjęty. ${statusWords(data)}.`)
          void queryClient.invalidateQueries()
        },
      },
    )
  }

  return (
    <form onSubmit={submit} className="grid gap-3 rounded-md border border-line bg-surface p-4">
      <h2 className="m-0 text-lg font-extrabold">Wpisz kod dostępu</h2>
      <TextField
        label="Kod (12 znaków)"
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        placeholder="ABCD-EFGH-JKMN"
        maxLength={40}
        autoComplete="off"
        spellCheck={false}
        hint="Spacje i myślniki nie mają znaczenia. Kod dotyczy całej firmy; pracownicy niczego nie wpisują."
      />
      {redeem.isError && <InlineError>{errorMessage(redeem.error, NETWORK_PROBLEM)}</InlineError>}
      {done && (
        <p role="status" className="m-0 font-semibold text-accent">
          {done}
        </p>
      )}
      <Button type="submit" size="normal" disabled={redeem.isPending || !code.trim()} className="w-fit">
        <KeyRound aria-hidden="true" size={20} />
        {redeem.isPending ? 'Sprawdzam kod…' : 'Użyj kodu'}
      </Button>
    </form>
  )
}
