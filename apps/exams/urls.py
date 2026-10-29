
from django.urls import path

from . import views

app_name = "exams"

urlpatterns = [
    path("create/", views.create_exam, name="create"),
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
        "attempt/<int:attempt_id>/submit/",
        views.submit_attempt,
        name="submit_attempt",
    ),
]
