import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { getMeQueryKey, useUpdateMe } from '../../api/generated/auth/auth'
import type { MeOut } from '../../api/generated/model'
import { Button } from '../../components/ui/button'
import { TextField } from '../../components/ui/field'
import { InlineError } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'

export function ProfileNameForm({ me }: { me: MeOut }) {
  const [first, setFirst] = useState(me.first_name)
  const [last, setLast] = useState(me.last_name)
  const save = useUpdateMe()
  const queryClient = useQueryClient()
  return (
    <form className="mx-auto grid max-w-(--column) gap-3 rounded-md border border-line bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate({ data: { first_name: first.trim(), last_name: last.trim() } }, {
          onSuccess: (response) => queryClient.setQueryData(getMeQueryKey(), response),
        })
      }}>
      <h2 className="m-0 text-lg font-bold">Jak podpisać Cię w grafiku?</h2>
      <TextField label="Imię" autoComplete="given-name" required maxLength={80} value={first} onChange={(e) => setFirst(e.target.value)} />
      <TextField label="Nazwisko" autoComplete="family-name" required maxLength={120} value={last} onChange={(e) => setLast(e.target.value)} />
      {save.isError && <InlineError>{errorMessage(save.error, NETWORK_PROBLEM)}</InlineError>}
      <Button type="submit" disabled={save.isPending || !first.trim() || !last.trim()}>Zapisz imię i nazwisko</Button>
    </form>
  )
}
