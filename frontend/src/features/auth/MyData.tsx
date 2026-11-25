import { useQueryClient } from '@tanstack/react-query'
import { UserRound } from 'lucide-react'
import { useState } from 'react'

import { getMeQueryKey, useUpdateMe } from '../../api/generated/auth/auth'
import type { MeIn, MeOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { TextField } from '../../components/ui/field'
import { Sheet } from '../../components/ui/sheet'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'
import { bankAccountDigits, prettyBankAccount } from './bank-account'
import { prettyPhone } from './phone'

/** "Twoje dane" at the top of the employee's screens: name and the bank account number for pay (optional). */
export function MyDataButton({ me, className }: { me: MeOut; className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={className}>
        <UserRound aria-hidden="true" size={18} />
        Twoje dane
      </button>
      <Sheet open={open} onOpenChange={setOpen} title="Twoje dane">
        {open && <MyDataForm me={me} onDone={() => setOpen(false)} />}
      </Sheet>
    </>
  )
}

export function MyDataForm({ me, onDone }: { me: MeOut; onDone: () => void }) {
  const [first, setFirst] = useState(me.first_name)
  const [last, setLast] = useState(me.last_name)
  const [account, setAccount] = useState(prettyBankAccount(me.bank_account ?? ''))
  const save = useUpdateMe()
  const queryClient = useQueryClient()

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const data: MeIn = { first_name: first.trim(), last_name: last.trim() }
    if (bankAccountDigits(account) !== (me.bank_account ?? '')) data.bank_account = account
    save.mutate(
      { data },
      {
        onSuccess: (response) => {
          queryClient.setQueryData(getMeQueryKey(), response)
          onDone()
        },
      },
    )
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Imię" autoComplete="given-name" required maxLength={80} value={first} onChange={(e) => setFirst(e.target.value)} />
        <TextField label="Nazwisko" autoComplete="family-name" required maxLength={120} value={last} onChange={(e) => setLast(e.target.value)} />
      </div>
      <TextField
        label="Numer konta do wypłaty"
        inputMode="numeric"
        autoComplete="off"
        maxLength={40}
        placeholder="26 cyfr"
        value={account}
        onChange={(e) => {
          setAccount(e.target.value)
          save.reset()
        }}
        hint="Nieobowiązkowy. Widzą go tylko Twoi kierownicy (też w pliku z godzinami) i administrator Grafikomatu."
      />
      <p className="m-0 text-sm text-ink-muted">{`Logujesz się numerem ${prettyPhone(me.phone)}.`}</p>
      {save.isError && <InlineError>{errorMessage(save.error, NETWORK_PROBLEM)}</InlineError>}
      <Button type="submit" wide disabled={save.isPending || !first.trim() || !last.trim()}>
        Zapisz dane
      </Button>
    </form>
  )
}
