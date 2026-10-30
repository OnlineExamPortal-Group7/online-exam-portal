from django.urls import path

from . import question_views as views

# Included from apps/exams/urls.py under "questions/"; names live in the "exams" namespace.
urlpatterns = [
    path("", views.QuestionListView.as_view(), name="question_list"),
    path("new/", views.QuestionCreateView.as_view(), name="question_create"),
    path("<int:pk>/", views.QuestionDetailView.as_view(), name="question_detail"),
    path("<int:pk>/edit/", views.QuestionUpdateView.as_view(), name="question_update"),
    path("<int:pk>/delete/", views.QuestionDeleteView.as_view(), name="question_delete"),
]
