from django.urls import path

from . import views

app_name = "results"

urlpatterns = [
    path("exams/", views.ExamResultListView.as_view(), name="exam_list"),
    path("exams/<int:pk>/", views.ExamResultReviewView.as_view(), name="exam_review"),
    path("exams/<int:pk>/publish/", views.PublishResultsView.as_view(), name="publish"),
]
