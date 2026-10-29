from django.urls import path

from . import views

app_name = "administration"

urlpatterns = [
    path("users/", views.UserListView.as_view(), name="user_list"),
]
