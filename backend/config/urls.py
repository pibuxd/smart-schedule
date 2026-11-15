from django.contrib import admin
from django.urls import path

from apps.core.admin_guard import admin_login
from config.api import api

urlpatterns = [
    path("api/admin/login/", admin_login),
    path("api/admin/", admin.site.urls),
    path("api/", api.urls),
]
