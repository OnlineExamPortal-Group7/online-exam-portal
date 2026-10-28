from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import home

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("exams/", include("apps.exams.urls")),
    path("results/", include("apps.results.urls")),
    path("manage/", include("apps.administration.urls")),
]
