"""Live examination monitoring routes (OEP-F-040), included under exams/monitor/."""
from django.urls import path

from . import monitoring

urlpatterns = [
    path("", monitoring.MonitorExamListView.as_view(), name="monitor_list"),
    path(
        "<int:pk>/",
        monitoring.MonitorExamDetailView.as_view(),
        name="monitor_detail",
    ),
    path(
        "<int:pk>/status/",
        monitoring.MonitorExamStatusView.as_view(),
        name="monitor_status",
    ),
]
