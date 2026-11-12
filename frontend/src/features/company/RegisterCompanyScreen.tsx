import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { getMeQueryKey } from '../../api/generated/auth/auth'
import type { CompanyOut, MeOut } from '../../api/generated/model'
import { useCreateCompany } from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { TextField } from '../../components/ui/field'
import { InlineError } from '../../components/ui/status'
import { Wordmark } from '../../components/Wordmark'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'

/**
 * Registering a company, after the phone number is confirmed: its name, the manager's name and (if they have one)
 * an access code. Without a code the company gets 14 days to try everything (decision of 12.11.2026).
 */
export function RegisterCompanyScreen({ me, onCreated }: { me: MeOut; onCreated: (companyId: string) => void }) {
  const create = useCreateCompany()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [firstName, setFirstName] = useState(me.first_name)
  const [lastName, setLastName] = useState(me.last_name)
  const [code, setCode] = useState('')
  const firstCompany = !me.companies.some((c) => c.role === 'owner')

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    create.mutate(
      { data: { name, first_name: firstName, last_name: lastName, code } },
      {
        onSuccess: async (response) => {
          const company = response.data as CompanyOut
          onCreated(company.id)
          await queryClient.invalidateQueries({ queryKey: getMeQueryKey() })
          await navigate({ to: '/kierownik' })
        },
      },
    )
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-(--column) flex-col gap-6 px-4 pt-6 pb-8">
      <Wordmark />
      <form className="mt-6 flex flex-1 flex-col gap-5" onSubmit={submit}>
        <div className="grid gap-2">
          <h1 className="m-0 text-2xl font-extrabold">Załóż firmę</h1>
          <p className="m-0 text-ink-muted">
            Firma to wszystkie Twoje lokale razem. Lokale, stanowiska i pracowników dodasz w następnym kroku.
          </p>
        </div>
        <TextField
          label="Nazwa firmy"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="np. Piekarnia Pod Lipą"
          required
          maxLength={200}
          autoFocus
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Twoje imię" value={firstName} onChange={(e) => setFirstName(e.target.value)} maxLength={80} />
          <TextField label="Nazwisko" value={lastName} onChange={(e) => setLastName(e.target.value)} maxLength={120} />
        </div>
        <TextField
          label="Kod dostępu (jeśli masz)"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="ABCD-EFGH-JKMN"
          maxLength={40}
          autoComplete="off"
          spellCheck={false}
          hint={
            firstCompany
              ? 'Bez kodu masz 14 dni na wypróbowanie wszystkiego. Kod możesz wpisać też później, w panelu kierownika.'
              : 'Okres próbny dostaje tylko pierwsza firma. Bez kodu ta firma będzie tylko do oglądania, dopóki go nie wpiszesz.'
          }
        />
        {create.isError && <InlineError>{errorMessage(create.error, NETWORK_PROBLEM)}</InlineError>}
        <div className="mt-auto grid gap-2">
          <Button type="submit" wide disabled={create.isPending || !name.trim()}>
            {create.isPending ? 'Zakładam firmę…' : 'Załóż firmę'}
          </Button>
          <Link
            to="/"
            className="inline-flex min-h-(--touch) items-center justify-center font-semibold text-accent underline underline-offset-4"
          >
            Nie teraz
          </Link>
        </div>
      </form>
    </main>
  )
}
