

from django.urls import include, path

from . import import_views, views

app_name = "exams"

urlpatterns = [
    path("questions/", include("apps.exams.question_urls")),
    path("monitor/", include("apps.exams.monitoring_urls")),

    # Examination management and publishing
    path("manage/", views.exam_list, name="exam_list"),
    path(
        "<int:exam_id>/publish/",
        views.publish_exam,
        name="publish_exam",
    ),

    # Examination creation
    path("create/", views.create_exam, name="create"),

    # Student examination attempts
    path(
        "<int:exam_id>/start/",
        views.start_attempt,
        name="start_attempt",
    ),
    path(
        "attempt/<int:attempt_id>/",
        views.take_attempt,
        name="take_attempt",
    ),
    path(
        "attempt/<int:attempt_id>/answer/",
        views.save_answer,
        name="save_answer",
    ),
    path(
        "attempt/<int:attempt_id>/autosave/",
        views.autosave_answer,
        name="autosave_answer",
    ),
    path(
        "attempt/<int:attempt_id>/submit/",
        views.submit_attempt,
        name="submit_attempt",
    ),

    # Question import
    path(
        "questions/import/",
        import_views.QuestionImportView.as_view(),
        name="question_import",
    ),
    path(
        "questions/import/sample.csv",
        import_views.SampleCsvView.as_view(),
        name="question_import_sample",
    ),
]
