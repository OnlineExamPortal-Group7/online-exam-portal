
"""Tests for class performance analytics (OEP-F-033)."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from . import services
from .test_services import ResultsTestData


class ClassPerformanceAnalyticsTest(ResultsTestData, TestCase):

    def test_analytics_requires_published_results(self):
        self.make_attempt(
            self.ended_exam, self.student, self.correct
        )

        with self.assertRaises(ValidationError):
            services.class_performance_analytics(self.ended_exam)

    def test_score_distribution_and_question_accuracy(self):
        self.make_attempt(
            self.ended_exam, self.student, self.correct
        )
        self.make_attempt(
            self.ended_exam, self.student2, self.wrong
        )

        services.publish_results(self.ended_exam, self.instructor)

        analytics = services.class_performance_analytics(
            self.ended_exam
        )

        self.assertEqual(analytics["scored_count"], 2)
        self.assertEqual(analytics["average_percentage"], 50.0)

        self.assertEqual(
            analytics["total_published_score"], 2
        )
        self.assertEqual(
            analytics["total_published_marks"], 4
        )

        distribution = {
            item["label"]: item["count"]
            for item in analytics["score_distribution"]
        }

        self.assertEqual(distribution["0-20%"], 1)
        self.assertEqual(distribution["80-100%"], 1)

        question = analytics["question_rows"][0]

        self.assertEqual(question["correct_count"], 1)
        self.assertEqual(question["attempt_count"], 2)
        self.assertEqual(question["correct_rate"], 50.0)

    def test_unanswered_question_counts_as_incorrect(self):
        self.make_attempt(
            self.ended_exam, self.student, self.correct
        )
        self.make_attempt(
            self.ended_exam, self.student2, choice=None
        )

        services.publish_results(self.ended_exam, self.instructor)

        analytics = services.class_performance_analytics(
            self.ended_exam
        )

        question = analytics["question_rows"][0]

        self.assertEqual(question["correct_count"], 1)
        self.assertEqual(question["attempt_count"], 2)
        self.assertEqual(question["correct_rate"], 50.0)

    def test_analytics_handles_exam_with_no_attempts(self):
        services.publish_results(self.ended_exam, self.instructor)

        analytics = services.class_performance_analytics(
            self.ended_exam
        )

        self.assertEqual(analytics["scored_count"], 0)
        self.assertEqual(analytics["average_percentage"], 0)
        self.assertEqual(analytics["total_published_score"], 0)
        self.assertEqual(analytics["total_published_marks"], 0)

        self.assertEqual(
            analytics["question_rows"][0]["correct_rate"], 0
        )
