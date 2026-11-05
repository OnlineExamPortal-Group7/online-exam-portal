
from django.urls import path

from . import views

app_name = "results"

urlpatterns = [
    # Instructor result review and publication (Issue #18)
    path("exams/", views.ExamResultListView.as_view(), name="exam_list"),
    path("exams/<int:pk>/", views.ExamResultReviewView.as_view(), name="exam_review"),
    path("exams/<int:pk>/publish/", views.PublishResultsView.as_view(), name="publish"),

    # Student results and examination history (Issue #19)
    path("student/", views.StudentResultsListView.as_view(), name="student_results"),
    path("student/history/", views.StudentExamHistoryView.as_view(), name="student_history"),
    path(
        "student/<int:pk>/",
        views.StudentResultDetailView.as_view(),
        name="student_result_detail",
    ),
]
