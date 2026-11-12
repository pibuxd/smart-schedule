import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { getMeQueryKey } from '../../api/generated/auth/auth'
import type { MyInvitationOut } from '../../api/generated/model'
import {
  getMyInvitationsQueryKey,
  useAcceptInvitation,
  useDeclineInvitation,
  useMyInvitations,
} from '../../api/generated/tenancy/tenancy'
import { Button } from '../../components/ui/button'
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/ui/status'
import { errorMessage, NETWORK_PROBLEM } from '../../lib/api-error'

const ROLE_WORDS: Record<MyInvitationOut['role'], string> = {
  employee: 'pracownik',
  manager: 'kierownik',
}

export function InvitationsScreen({ name }: { name: string }) {
  const invitations = useMyInvitations()

  return (
    <main className="mx-auto grid max-w-(--column) gap-5 px-4 pt-6 pb-10">
      {name && <p className="m-0 text-sm text-ink-muted">{name}</p>}
      <h1 className="m-0 text-xl font-extrabold">Zaproszenia do pracy</h1>
      {invitations.isPending ? (
        <Loading>Sprawdzam zaproszenia…</Loading>
      ) : invitations.isError ? (
        <ErrorState onRetry={() => void invitations.refetch()}>
          Nie udało się wczytać zaproszeń. Sprawdź internet i spróbuj jeszcze raz.
        </ErrorState>
      ) : (invitations.data.data as MyInvitationOut[]).length === 0 ? (
        <EmptyState title="Nie masz żadnych zaproszeń">
          <p className="m-0">
            Gdy kierownik zaprosi Cię do pracy na ten numer telefonu, zaproszenie pojawi się tutaj.
          </p>
          <Link to="/" className="font-semibold text-accent underline underline-offset-4">
            Wróć do grafiku
          </Link>
        </EmptyState>
      ) : (
        (invitations.data.data as MyInvitationOut[]).map((invitation) => (
          <InvitationCard key={invitation.id} invitation={invitation} />
        ))
      )}
    </main>
  )
}

function InvitationCard({ invitation }: { invitation: MyInvitationOut }) {
  const [confirmDecline, setConfirmDecline] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const accept = useAcceptInvitation()
  const decline = useDeclineInvitation()
  const busy = accept.isPending || decline.isPending

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: getMyInvitationsQueryKey() })
    await queryClient.invalidateQueries({ queryKey: getMeQueryKey() })
  }

  return (
    <article className="grid gap-4 rounded-lg border border-line bg-surface p-5">
      <h2 className="m-0 text-lg font-extrabold">{invitation.company_name}</h2>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
        <dt className="text-ink-muted">Lokal</dt>
        <dd className="m-0 font-semibold">{invitation.location_name}</dd>
        {invitation.location_address && (
          <>
            <dt className="text-ink-muted">Adres</dt>
            <dd className="m-0 font-semibold">{invitation.location_address}</dd>
          </>
        )}
        {invitation.invited_by_name && (
          <>
            <dt className="text-ink-muted">Zaprasza</dt>
            <dd className="m-0 font-semibold">{invitation.invited_by_name}</dd>
          </>
        )}
        <dt className="text-ink-muted">Jako</dt>
        <dd className="m-0 font-semibold">{ROLE_WORDS[invitation.role]}</dd>
      </dl>
      {confirmDecline ? (
        <div className="grid gap-3 rounded-md bg-cannot-soft p-4">
          <p className="m-0">
            Na pewno odrzucić? Żeby dołączyć później, kierownik musi zaprosić Cię jeszcze raz.
          </p>
          <Button
            variant="danger"
            wide
            disabled={busy}
            onClick={() => decline.mutate({ invitationId: invitation.id }, { onSuccess: refresh })}
          >
            Tak, odrzucam
          </Button>
          <Button variant="secondary" wide disabled={busy} onClick={() => setConfirmDecline(false)}>
            Wróć
          </Button>
        </div>
      ) : (
        <>
          <p className="m-0 text-ink-muted">
            Po przyjęciu zobaczysz tu swój grafik i zaznaczysz, kiedy możesz pracować.
          </p>
          <div className="grid gap-2">
            <Button
              wide
              disabled={busy}
              onClick={() =>
                accept.mutate(
                  { invitationId: invitation.id },
                  {
                    onSuccess: async () => {
                      await refresh()
                      await navigate({ to: '/' })
                    },
                  },
                )
              }
            >
              {accept.isPending ? 'Przyjmuję…' : 'Przyjmuję zaproszenie'}
            </Button>
            <Button variant="secondary" wide disabled={busy} onClick={() => setConfirmDecline(true)}>
              Odrzucam
            </Button>
          </div>
        </>
      )}
      {(accept.isError || decline.isError) && (
        <InlineError>{errorMessage(accept.error ?? decline.error, NETWORK_PROBLEM)}</InlineError>
      )}
    </article>
  )
}
