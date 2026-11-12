"""The logged-in person's own employee profile in one company (for the employee screens)."""

from uuid import UUID

from ninja.errors import HttpError

from apps.staffing.models import EmployeeProfile
from apps.tenancy.context import TenantContext, tenant_context

NO_PROFILE = "Nie jesteś pracownikiem w tej firmie. Poproś kierownika o zaproszenie."


def employee_context(request, company_id: UUID | str) -> tuple[TenantContext, EmployeeProfile]:
    """Tenant context plus my active employee profile; 404 when I have none in this company."""
    ctx = tenant_context(request, company_id)
    profile = (
        ctx.qs(EmployeeProfile)
        .filter(membership=ctx.membership, is_active=True)
        .select_related("home_location", "membership__user")
        .first()
    )
    if profile is None:
        raise HttpError(404, NO_PROFILE)
    return ctx, profile
