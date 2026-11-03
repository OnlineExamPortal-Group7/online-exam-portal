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
    path("courses/<int:pk>/", views.CourseDetailView.as_view(), name="course_detail"),
    path("courses/<int:pk>/edit/", views.CourseUpdateView.as_view(), name="course_edit"),
    path("courses/<int:pk>/enrol/", views.CourseEnrolView.as_view(), name="course_enrol"),
    path("courses/<int:pk>/unenrol/", views.CourseUnenrolView.as_view(), name="course_unenrol"),
    path(
        "courses/<int:pk>/deactivate/",
        views.CourseDeactivateView.as_view(),
        name="course_deactivate",
    ),
    path(
        "courses/<int:pk>/reactivate/",
        views.CourseReactivateView.as_view(),
        name="course_reactivate",
    ),
]
