from ninja import NinjaAPI

from apps.core.api import router as core_router


class GrafikomatAPI(NinjaAPI):
    def get_openapi_operation_id(self, operation) -> str:
        # Short, stable ids so the generated frontend client reads well (e.g. `useHealth`).
        return operation.view_func.__name__


api = GrafikomatAPI(title="Grafikomat API", version="0.1.0", urls_namespace="api")
api.add_router("/", core_router)
