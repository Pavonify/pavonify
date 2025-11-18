import io
from typing import Dict, List

import pandas as pd
from django.http import HttpResponse
from django.shortcuts import render


def _clean_cell(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def isams_transform_view(request):
    context = {"stage": "upload"}
    error_message = None

    if request.method == "POST":
        stage = request.POST.get("stage")

        if stage == "preview":
            academic_year = request.POST.get("academic_year", "").strip()
            reporting_cycle = request.POST.get("reporting_cycle", "").strip()
            uploaded_file = request.FILES.get("report_file")

            if not uploaded_file:
                error_message = "Please upload an iSAMS Excel report file."
            else:
                try:
                    df = pd.read_excel(
                        uploaded_file, engine="openpyxl", header=None
                    )
                except Exception:
                    error_message = "Unable to read the uploaded Excel file. Please ensure it is a valid .xlsx file."
                else:
                    df = df.drop(index=0).reset_index(drop=True)
                    if df.shape[0] < 3:
                        error_message = (
                            "The uploaded file does not have the expected header rows."
                        )
                    else:
                        df.iloc[0] = df.iloc[0].ffill()
                        df.iloc[1] = df.iloc[1].ffill()

                        subject_row = df.iloc[0]
                        metric_row = df.iloc[2]

                        subject_values = subject_row.iloc[2:]
                        subject_codes = sorted(
                            {
                                cleaned
                                for cleaned in (_clean_cell(val) for val in subject_values)
                                if cleaned
                            }
                        )

                        metric_values = metric_row.iloc[2:]
                        metrics = sorted(
                            {
                                cleaned
                                for cleaned in (_clean_cell(val) for val in metric_values)
                                if cleaned
                            }
                        )

                        if not subject_codes or not metrics:
                            error_message = (
                                "Unable to detect subjects or metrics in the uploaded file."
                            )
                        else:
                            request.session["isams_df"] = df.to_json(orient="split")
                            request.session["isams_academic_year"] = academic_year
                            request.session["isams_reporting_cycle"] = reporting_cycle

                            subject_entries = [
                                {"index": idx, "code": code, "display_name": code}
                                for idx, code in enumerate(subject_codes)
                            ]

                            context.update(
                                {
                                    "stage": "preview",
                                    "academic_year": academic_year,
                                    "reporting_cycle": reporting_cycle,
                                    "subject_codes": subject_entries,
                                    "metrics": metrics,
                                    "subject_count": len(subject_entries),
                                }
                            )

        elif stage == "transform":
            if "isams_df" not in request.session:
                error_message = "Session expired. Please upload your file again."
            else:
                try:
                    df = pd.read_json(request.session["isams_df"], orient="split")
                except Exception:
                    error_message = "Unable to load the stored file data. Please restart the process."
                else:
                    selected_metrics = request.POST.getlist("metrics")
                    if not selected_metrics:
                        error_message = "Please select at least one metric to include."
                    else:
                        try:
                            subject_count = int(request.POST.get("subject_count", 0))
                        except (TypeError, ValueError):
                            subject_count = 0

                        subject_map: Dict[str, str] = {}
                        for i in range(subject_count):
                            code = request.POST.get(f"subject_code_{i}")
                            name = request.POST.get(f"subject_name_{i}")
                            code_clean = _clean_cell(code)
                            name_clean = _clean_cell(name) or code_clean
                            if code_clean:
                                subject_map[code_clean] = name_clean or code_clean

                        academic_year = request.session.get("isams_academic_year", "")
                        reporting_cycle = request.session.get("isams_reporting_cycle", "")

                        try:
                            result = _transform_dataframe(
                                df,
                                selected_metrics,
                                subject_map,
                                academic_year,
                                reporting_cycle,
                            )
                        except ValueError as exc:
                            error_message = str(exc)
                        else:
                            buffer = io.StringIO()
                            result.to_csv(buffer, index=False)
                            buffer.seek(0)

                            response = HttpResponse(
                                buffer.getvalue(),
                                content_type="text/csv",
                            )
                            response[
                                "Content-Disposition"
                            ] = 'attachment; filename="isams_reporting_long.csv"'

                            for key in [
                                "isams_df",
                                "isams_academic_year",
                                "isams_reporting_cycle",
                            ]:
                                request.session.pop(key, None)

                            return response

    if error_message:
        context["error_message"] = error_message

    return render(request, "isams_transform.html", context)


def _transform_dataframe(
    df: pd.DataFrame,
    selected_metrics: List[str],
    subject_map: Dict[str, str],
    academic_year: str,
    reporting_cycle: str,
) -> pd.DataFrame:
    if df.shape[0] < 3:
        raise ValueError("The stored report data is missing header rows.")

    df = df.copy()
    df.iloc[0] = df.iloc[0].ffill()
    df.iloc[1] = df.iloc[1].ffill()

    subject_row = df.iloc[0]
    teacher_row = df.iloc[1]
    metric_row = df.iloc[2]

    meta_rows = []
    for col in df.columns[2:]:
        subject_code = _clean_cell(subject_row.loc[col])
        teacher_code = _clean_cell(teacher_row.loc[col])
        metric_name = _clean_cell(metric_row.loc[col])

        if not subject_code or not metric_name:
            continue
        if metric_name not in selected_metrics:
            continue

        meta_rows.append(
            {
                "col_name": col,
                "subject_code": subject_code,
                "teacher_code": teacher_code,
                "metric_name": metric_name,
            }
        )

    if not meta_rows:
        raise ValueError("No columns matched the selected metrics.")

    meta = pd.DataFrame(meta_rows)

    data = df.iloc[3:].copy()
    data.reset_index(drop=True, inplace=True)

    if data.shape[1] < 2:
        raise ValueError("Student name and ID columns are missing.")

    name_col = data.columns[0]
    id_col = data.columns[1]
    data = data.rename(columns={name_col: "StudentName", id_col: "StudentID"})

    value_cols = meta["col_name"].tolist()

    long_df = data.melt(
        id_vars=["StudentName", "StudentID"],
        value_vars=value_cols,
        var_name="col_name",
        value_name="MetricValue",
    )

    long_df = long_df.merge(meta, on="col_name", how="left")
    long_df.drop(columns=["col_name"], inplace=True)

    long_df = long_df.dropna(subset=["MetricValue"])
    long_df = long_df[long_df["MetricValue"].astype(str).str.strip() != ""]

    long_df["SubjectName"] = (
        long_df["subject_code"].map(subject_map).fillna(long_df["subject_code"])
    )
    long_df["AcademicYear"] = academic_year
    long_df["ReportingCycle"] = reporting_cycle

    long_df = long_df.rename(
        columns={
            "subject_code": "SubjectCode",
            "teacher_code": "TeacherCode",
            "metric_name": "MetricName",
        }
    )

    final_cols = [
        "StudentID",
        "StudentName",
        "SubjectCode",
        "SubjectName",
        "TeacherCode",
        "MetricName",
        "MetricValue",
        "AcademicYear",
        "ReportingCycle",
    ]

    long_df = long_df[final_cols]
    return long_df
