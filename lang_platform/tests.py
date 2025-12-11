from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from unittest.mock import patch

import pandas as pd

from .views import _calculate_ib_scores, _pivot_long_to_wide, isams_transform_view


def _add_session(request):
    """Attach a working session to a RequestFactory request."""

    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()


class IsamsTransformMetricsTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        df = pd.DataFrame(
            [
                [None, None, "ENG", "ENG", "MAT", "MAT"],
                [None, None, "T1", "T1", "T2", "T2"],
                [
                    None,
                    None,
                    "Assessment Grade",
                    "End of Semester Examination Grade",
                    "Assessment Grade",
                    "End of Semester Examination Grade",
                ],
                ["Alice", "1", "A", "A*", "B", "B+"],
            ]
        )

        self.serialised_df = df.to_json(orient="split")

    def test_multiple_metrics_are_passed_to_transform(self):
        request = self.factory.post(
            "/isams-transform/",
            data={
                "stage": "transform",
                "subject_count": "0",
                "metrics[]": [
                    " Assessment Grade ",
                    "End of Semester Examination Grade",
                    "Flight Path Grade",
                ],
            },
        )
        _add_session(request)
        request.session["isams_df"] = self.serialised_df
        request.session["isams_academic_year"] = "2023-24"
        request.session["isams_reporting_cycle"] = "S1"

        with patch("lang_platform.views._transform_dataframe") as mock_transform:
            mock_transform.return_value = pd.DataFrame()

            response = isams_transform_view(request)

        self.assertEqual(response.status_code, 200)

        selected_metrics = mock_transform.call_args[0][1]
        self.assertListEqual(
            selected_metrics,
            [
                "Assessment Grade",
                "End of Semester Examination Grade",
                "Flight Path Grade",
            ],
        )


class IsamsLongToWideTest(TestCase):
    def test_pivot_creates_subject_and_metric_columns(self):
        df = pd.DataFrame(
            [
                {
                    "StudentID": "1",
                    "StudentName": "Alice",
                    "SubjectName": "Math",
                    "MetricName": "Exam grade",
                    "MetricValue": "A*",
                },
                {
                    "StudentID": "1",
                    "StudentName": "Alice",
                    "SubjectName": "Math",
                    "MetricName": "Assessment grade",
                    "MetricValue": "B",
                },
                {
                    "StudentID": "2",
                    "StudentName": "Bob",
                    "SubjectName": "Art",
                    "MetricName": "Assessment grade",
                    "MetricValue": "A",
                },
            ]
        )

        wide = _pivot_long_to_wide(
            df,
            row_identifiers=["StudentID", "StudentName"],
            column_groups=["SubjectName", "MetricName"],
            value_column="MetricValue",
        )

        self.assertListEqual(
            wide.columns.tolist(),
            ["StudentID", "StudentName", "Art_Assessment grade", "Math_Assessment grade", "Math_Exam grade"],
        )
        self.assertEqual(wide.loc[wide["StudentID"] == "1", "Math_Exam grade"].iloc[0], "A*")

    def test_missing_required_columns_raise_error(self):
        df = pd.DataFrame([{"StudentID": 1, "Value": "A"}])

        with self.assertRaises(ValueError):
            _pivot_long_to_wide(
                df,
                row_identifiers=["StudentID"],
                column_groups=["SubjectName"],
                value_column="MetricValue",
            )


class IsamsIBCalculateTest(TestCase):
    def setUp(self):
        subjects = [
            ("Math HL", 6, "6+"),
            ("Physics HL", 6, "6-"),
            ("Chemistry HL", 7, "7"),
            ("History SL", 5, "5+"),
            ("English SL", 6, "6"),
            ("Spanish SL", 6, "6+"),
            ("TOK", 7, "7"),
        ]

        rows = []
        for name, assessment, flight in subjects:
            rows.append(
                {
                    "StudentName": "Alice",
                    "SubjectName": name,
                    "SubjectCode": name,
                    "MetricName": "Assessment grade",
                    "MetricValue": assessment,
                }
            )
            rows.append(
                {
                    "StudentName": "Alice",
                    "SubjectName": name,
                    "SubjectCode": name,
                    "MetricName": "Flight Path grade",
                    "MetricValue": flight,
                }
            )

        for name, assessment, flight in subjects[:4]:
            rows.append(
                {
                    "StudentName": "Bob",
                    "SubjectName": name,
                    "SubjectCode": name,
                    "MetricName": "Assessment grade",
                    "MetricValue": assessment,
                }
            )
            rows.append(
                {
                    "StudentName": "Bob",
                    "SubjectName": name,
                    "SubjectCode": name,
                    "MetricName": "Flight Path grade",
                    "MetricValue": flight,
                }
            )

        self.df = pd.DataFrame(rows)

    def test_calculations_total_scores_and_subjects(self):
        result = _calculate_ib_scores(self.df)

        self.assertIn("StudentName", result.columns)
        self.assertIn("AssessmentTotal", result.columns)
        self.assertIn("FlightPathTotal", result.columns)
        self.assertIn("ValidSubjects", result.columns)

        alice_row = result[result["StudentName"] == "Alice"].iloc[0]
        self.assertEqual(alice_row["AssessmentTotal"], 36)
        self.assertEqual(alice_row["FlightPathTotal"], 36)
        self.assertEqual(alice_row["ValidSubjects"], "Y")

        subject_columns = [col for col in result.columns if col.startswith("Subject ")]
        subjects_listed = alice_row[subject_columns].tolist()
        self.assertIn("Math HL", subjects_listed)
        self.assertIn("Spanish SL", subjects_listed)

        bob_row = result[result["StudentName"] == "Bob"].iloc[0]
        self.assertEqual(bob_row["ValidSubjects"], "")

    def test_calculations_respect_manual_exclusions(self):
        result = _calculate_ib_scores(self.df, user_exclusions={"spanish sl"})

        alice_row = result[result["StudentName"] == "Alice"].iloc[0]
        self.assertEqual(alice_row["AssessmentTotal"], 30)
        self.assertEqual(alice_row["FlightPathTotal"], 30)
        self.assertEqual(alice_row["ValidSubjects"], "")
