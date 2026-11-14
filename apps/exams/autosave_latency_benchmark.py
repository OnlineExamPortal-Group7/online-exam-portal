"""Diagnostic benchmark for the exam autosave endpoint."""

from math import ceil
from time import perf_counter

from django.urls import reverse

from .test_autosave import AutosaveTestBase


class AutosaveLatencyBenchmark(AutosaveTestBase):
    """Measure local Django test-client autosave response latency."""

    def test_measure_autosave_latency(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        url = reverse("exams:autosave_answer", args=[attempt.pk])
        question = self.questions[0]
        choice = self.correct[0]

        # Warm-up request (excluded from measurements).
        warmup = self.client.post(
            url,
            {
                "question_id": question.pk,
                "choice_id": choice.pk,
                "seq": 1,
            },
        )
        self.assertEqual(warmup.status_code, 200)
        self.assertTrue(warmup.json()["saved"])

        latencies_ms = []

        for seq in range(2, 102):
            start = perf_counter()

            response = self.client.post(
                url,
                {
                    "question_id": question.pk,
                    "choice_id": choice.pk,
                    "seq": seq,
                },
            )

            elapsed_ms = (perf_counter() - start) * 1000
            latencies_ms.append(elapsed_ms)

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["saved"])

        sorted_times = sorted(latencies_ms)
        average = sum(latencies_ms) / len(latencies_ms)
        median = (
            sorted_times[49] + sorted_times[50]
        ) / 2
        p95 = sorted_times[ceil(0.95 * len(sorted_times)) - 1]
        maximum = max(latencies_ms)

        print("\n--- AUTOSAVE LATENCY BENCHMARK ---")
        print("Requests measured: 100")
        print(f"Average: {average:.3f} ms")
        print(f"Median:  {median:.3f} ms")
        print(f"P95:     {p95:.3f} ms")
        print(f"Maximum: {maximum:.3f} ms")
        print("----------------------------------")
