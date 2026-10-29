from django.urls import path

from . import views

app_name = "administration"

urlpatterns = [
    path("users/", views.UserListView.as_view(), name="user_list"),
    path("users/new/", views.UserCreateView.as_view(), name="user_create"),
    path("users/<int:pk>/deactivate/", views.UserDeactivateView.as_view(), name="user_deactivate"),
    path("users/<int:pk>/reactivate/", views.UserReactivateView.as_view(), name="user_reactivate"),
    path("users/<int:pk>/role/", views.UserRoleChangeView.as_view(), name="user_role"),
]
