from ninja import NinjaAPI
from ninja.errors import AuthenticationError
from ninja.security import django_auth

from apps.accounts.api import router as accounts_router
from apps.billing.api import router as billing_router
from apps.core.api import router as core_router
from apps.tenancy.api import router as tenancy_router


class GrafikomatAPI(NinjaAPI):
    def get_openapi_operation_id(self, operation) -> str:
        # Short, stable ids so the generated frontend client reads well (e.g. `useHealth`).
        return operation.view_func.__name__


# Every endpoint needs a logged-in session (with a CSRF check on unsafe methods) unless it says `auth=None`.
api = GrafikomatAPI(title="Grafikomat API", version="0.1.0", urls_namespace="api", auth=django_auth)
api.add_router("/", core_router)
api.add_router("/", accounts_router)
api.add_router("/", tenancy_router)
api.add_router("/", billing_router)


@api.exception_handler(AuthenticationError)
def not_logged_in(request, exc):
    return api.create_response(request, {"detail": "Zaloguj się."}, status=401)
