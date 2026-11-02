from django.urls import path

from . import views

app_name = "administration"

urlpatterns = [
    path("users/", views.UserListView.as_view(), name="user_list"),
    path("users/new/", views.UserCreateView.as_view(), name="user_create"),
    path("users/<int:pk>/deactivate/", views.UserDeactivateView.as_view(), name="user_deactivate"),
    path("users/<int:pk>/reactivate/", views.UserReactivateView.as_view(), name="user_reactivate"),
    path("users/<int:pk>/role/", views.UserRoleChangeView.as_view(), name="user_role"),
    path("courses/", views.CourseListView.as_view(), name="course_list"),
    path("courses/new/", views.CourseCreateView.as_view(), name="course_create"),
    path("courses/<int:pk>/edit/", views.CourseUpdateView.as_view(), name="course_edit"),
]
