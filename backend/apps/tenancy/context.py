"""The single entry point for company data in API code.

Every company endpoint starts with `ctx = tenant_context(request, company_id)` and reads only through
`ctx.qs(Model)` / `ctx.get(Model, ...)`. A user who is not a member of the company gets 404, never 403,
so the API does not reveal that another company's object exists. `tests/test_tenant_guard.py` fails when
an `api.py` file reads a company-owned model through plain `Model.objects`.

Endpoints addressed by an object id alone (e.g. `/locations/{id}/...`) start with
`ctx, obj = context_for(request, Model, object_id)`.

Every endpoint that changes company data also calls `ctx.require_writable()`: a company whose access has
expired (or that never entered a code) is read-only.
"""

from dataclasses import dataclass
from uuid import UUID

from django.db.models import Model, QuerySet
from ninja.errors import HttpError

from apps.tenancy.base import is_company_owned
from apps.tenancy.models import Company, Location, Membership, Role


@dataclass(frozen=True)
class TenantContext:
    company: Company
    membership: Membership

    @property
    def user(self):
        return self.membership.user

    @property
    def role(self) -> str:
        return self.membership.role

    @property
    def is_manager(self) -> bool:
        return self.membership.is_manager

    def qs[M: Model](self, model: type[M]) -> QuerySet[M]:
        if not is_company_owned(model):
            raise TypeError(f"{model.__name__} is not company-owned")
        return model.objects.for_company(self.company)

    def get[M: Model](self, model: type[M], **lookup) -> M:
        """One object of this company, or 404 (also when it exists in another company)."""
        obj = self.qs(model).filter(**lookup).first()
        if obj is None:
            raise HttpError(404, "Nie znaleziono.")
        return obj

    def managed_locations(self) -> QuerySet[Location]:
        """Locations this person manages: all for an owner, assigned ones for a manager, none for an employee."""
        locations = self.qs(Location)
        if self.role == Role.OWNER:
            return locations
        if self.role == Role.MANAGER:
            return locations.filter(managers=self.membership)
        return locations.none()

    def require_manager(self) -> None:
        if not self.is_manager:
            raise HttpError(403, "Ta czynność jest dostępna tylko dla menedżera.")

    def require_manager_of(self, location: Location) -> None:
        """The owner, or a manager assigned to this location."""
        if not self.managed_locations().filter(pk=location.pk).exists():
            raise HttpError(403, "Ta czynność jest dostępna tylko dla menedżera tego lokalu.")

    def require_writable(self) -> None:
        """Refuse changes when the company's access has expired (402, so the frontend can tell it apart)."""
        from apps.billing.services import subscription_state

        state = subscription_state(self.company.pk)
        if state.read_only:
            raise HttpError(402, state.read_only_message)


def tenant_context(request, company_id: UUID | str) -> TenantContext:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise HttpError(401, "Zaloguj się.")
    membership = Membership.objects.select_related("company", "user").filter(user=user, company_id=company_id).first()
    if membership is None:
        raise HttpError(404, "Nie znaleziono.")
    return TenantContext(company=membership.company, membership=membership)


def context_for[M: Model](request, model: type[M], object_id: UUID | str) -> tuple[TenantContext, M]:
    """Tenant context found from a company-owned object: 404 when it does not exist or is another company's."""
    if not is_company_owned(model):
        raise TypeError(f"{model.__name__} is not company-owned")
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise HttpError(401, "Zaloguj się.")
    company_id = model._base_manager.filter(pk=object_id).values_list("company_id", flat=True).first()
    if company_id is None:
        raise HttpError(404, "Nie znaleziono.")
    ctx = tenant_context(request, company_id)
    return ctx, ctx.get(model, pk=object_id)
