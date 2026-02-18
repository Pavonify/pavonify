import io
from typing import Dict, List, Sequence

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
                    selected_metrics_raw = request.POST.getlist("metrics")
                    if not selected_metrics_raw:
                        selected_metrics_raw = request.POST.getlist("metrics[]")

                    selected_metrics = [
                        metric
                        for metric in (
                            _clean_cell(metric_value) for metric_value in selected_metrics_raw
                        )
                        if metric
                    ]
                    selected_metrics = list(dict.fromkeys(selected_metrics))

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
                        exclude_dash = request.POST.get("exclude_dash") not in (
                            None,
                            "",
                            "false",
                            "False",
                            "0",
                        )

                        try:
                            result = _transform_dataframe(
                                df,
                                selected_metrics,
                                subject_map,
                                academic_year,
                                reporting_cycle,
                                exclude_dash_values=exclude_dash,
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
    exclude_dash_values: bool = False,
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
    if exclude_dash_values:
        long_df = long_df[long_df["MetricValue"].astype(str).str.strip() != "-"]

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


def _pivot_long_to_wide(
    df: pd.DataFrame,
    row_identifiers: Sequence[str],
    column_groups: Sequence[str],
    value_column: str,
) -> pd.DataFrame:
    if not row_identifiers:
        raise ValueError("Please select at least one column to define the rows.")

    if not column_groups:
        raise ValueError("Please select at least one column to define the column headers.")

    missing_cols = [
        col
        for col in list(row_identifiers) + list(column_groups) + [value_column]
        if col not in df.columns
    ]

    if missing_cols:
        raise ValueError(
            "The uploaded file is missing the following columns: "
            + ", ".join(missing_cols)
        )

    work_df = df.copy()
    work_df = work_df[row_identifiers + list(column_groups) + [value_column]]

    for col in column_groups:
        work_df[col] = work_df[col].apply(_clean_cell)

    pivot = work_df.pivot_table(
        index=list(row_identifiers),
        columns=list(column_groups),
        values=value_column,
        aggfunc="first",
    )

    pivot = pivot.sort_index(axis=1)
    pivot.reset_index(inplace=True)
    pivot.columns.name = None

    flat_columns = []
    for col in pivot.columns:
        if isinstance(col, tuple):
            parts = [str(part).strip() for part in col if part not in (None, "")]
            flat_columns.append("_".join(parts))
        else:
            flat_columns.append(str(col))

    pivot.columns = flat_columns
    return pivot


def _read_uploaded_table(uploaded_file):
    """Read an uploaded CSV or Excel file into a DataFrame."""

    name = (uploaded_file.name or "").lower()

    if name.endswith(".xlsx"):
        return pd.read_excel(uploaded_file, engine="openpyxl")

    try:
        return pd.read_csv(uploaded_file)
    except Exception:
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, engine="openpyxl")


def isams_ib_calculate_view(request):
    context = {"stage": "upload"}
    error_message = None

    if request.method == "POST":
        stage = request.POST.get("stage", "upload")

        if stage == "preview":
            uploaded_file = request.FILES.get("ib_long_file")

            if not uploaded_file:
                error_message = "Please upload the long-format IB sheet generated by the iSAMS transformer."
            else:
                try:
                    df = _read_uploaded_table(uploaded_file)
                except Exception:
                    error_message = "Unable to read the uploaded file. Please upload a valid CSV or Excel document."
                else:
                    try:
                        subjects = _list_ib_subjects(df)
                    except ValueError as exc:
                        error_message = str(exc)
                    else:
                        if not subjects:
                            error_message = "No subjects were detected in the uploaded file."
                        else:
                            request.session["ib_long_df"] = df.to_json(orient="split")
                            request.session["ib_subject_choices"] = subjects

                            context.update(
                                {
                                    "stage": "preview",
                                    "subjects": subjects,
                                    "filename": uploaded_file.name,
                                }
                            )

        elif stage == "calculate":
            if "ib_long_df" not in request.session:
                error_message = "Session expired. Please upload your file again."
            else:
                try:
                    df = pd.read_json(request.session["ib_long_df"], orient="split")
                except Exception:
                    error_message = "Unable to load the stored file data. Please restart the process."
                else:
                    subjects = request.session.get("ib_subject_choices", [])
                    included = request.POST.getlist("subjects")
                    included_normalised = {str(item).strip().lower() for item in included if str(item).strip()}

                    if not included_normalised:
                        error_message = "Please keep at least one subject selected to calculate totals."
                    else:
                        excluded = set()
                        for subject in subjects:
                            identifier = subject.get("identifier")
                            if not identifier:
                                continue
                            if identifier.strip().lower() not in included_normalised:
                                excluded.add(identifier.strip().lower())

                        try:
                            result = _calculate_ib_scores(df, user_exclusions=excluded)
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
                            ] = 'attachment; filename="isams_ib_calculations.csv"'

                            for key in ["ib_long_df", "ib_subject_choices"]:
                                request.session.pop(key, None)

                            return response

    if error_message:
        context["error_message"] = error_message

    return render(request, "isams_ib_calculate.html", context)


def _identify_metric_type(metric_name: str):
    if not metric_name:
        return None

    name = str(metric_name).strip().lower()
    if "assessment" in name and "grade" in name:
        return "assessment"
    if "flight" in name and "path" in name and "grade" in name:
        return "flight_path"
    return None


def _strip_grade_symbols(value: str) -> str:
    if value is None:
        return ""
    return str(value).replace("+", "").replace("-", "").strip()


def _parse_ib_grade(value) -> float | None:
    cleaned = _strip_grade_symbols(value)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _detect_ib_level(subject_name: str | None, subject_code: str | None) -> str | None:
    candidates = [subject_name, subject_code]
    for candidate in candidates:
        if not candidate:
            continue
        text = str(candidate).lower()
        tokens = text.replace("(", " ").replace(")", " ").replace("/", " ").split()
        if "hl" in tokens:
            return "HL"
        if "sl" in tokens:
            return "SL"
    return None


def _list_ib_subjects(df: pd.DataFrame) -> List[Dict[str, str]]:
    if "SubjectName" not in df.columns and "SubjectCode" not in df.columns:
        raise ValueError("The uploaded file must include SubjectName or SubjectCode columns.")

    working_df = df.copy()
    if "SubjectName" in working_df.columns:
        working_df["SubjectName"] = working_df["SubjectName"].apply(_clean_cell)
    else:
        working_df["SubjectName"] = ""

    if "SubjectCode" in working_df.columns:
        working_df["SubjectCode"] = working_df["SubjectCode"].apply(_clean_cell)
    else:
        working_df["SubjectCode"] = ""

    subjects = []
    seen = set()

    for _, row in working_df.iterrows():
        name = row.get("SubjectName")
        code = row.get("SubjectCode")
        identifier = name or code

        if not identifier:
            continue

        normalised = str(identifier).strip().lower()
        if normalised in seen:
            continue

        seen.add(normalised)
        subjects.append(
            {
                "identifier": identifier,
                "name": name or "",
                "code": code or "",
                "is_auto_excluded": _is_excluded_ib_subject(name, code),
            }
        )

    subjects = sorted(subjects, key=lambda s: s.get("name") or s.get("code") or "")
    return subjects


def _is_excluded_ib_subject(
    subject_name: str | None,
    subject_code: str | None,
    user_exclusions: set[str] | None = None,
) -> bool:
    excluded = {"tok", "cas", "ee"}
    for candidate in (subject_name, subject_code):
        if not candidate:
            continue
        text = str(candidate).strip().lower()
        if user_exclusions and text in user_exclusions:
            return True
        for code in excluded:
            if text == code or text.startswith(f"{code} "):
                return True
    return False


def _calculate_ib_scores(df: pd.DataFrame, user_exclusions: set[str] | None = None) -> pd.DataFrame:
    required_columns = {"StudentName", "SubjectName", "MetricName", "MetricValue"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(
            "The uploaded file is missing the following columns: "
            + ", ".join(sorted(missing))
        )

    if user_exclusions:
        user_exclusions = {str(item).strip().lower() for item in user_exclusions if str(item).strip()}

    working_df = df.copy()
    for col in required_columns:
        working_df[col] = working_df[col].apply(_clean_cell)

    working_df = working_df.dropna(subset=["StudentName", "SubjectName", "MetricName", "MetricValue"])

    working_df["metric_type"] = working_df["MetricName"].apply(_identify_metric_type)
    working_df = working_df[working_df["metric_type"].notna()]

    if working_df.empty:
        raise ValueError("No Assessment grade or Flight Path grade rows were found in the file.")

    working_df["SubjectLevel"] = working_df.apply(
        lambda row: _detect_ib_level(row.get("SubjectName"), row.get("SubjectCode")),
        axis=1,
    )
    working_df["IsExcluded"] = working_df.apply(
        lambda row: _is_excluded_ib_subject(
            row.get("SubjectName"), row.get("SubjectCode"), user_exclusions
        ),
        axis=1,
    )

    working_df["NumericValue"] = working_df["MetricValue"].apply(_parse_ib_grade)
    working_df = working_df[working_df["NumericValue"].notna()]

    valid_rows = working_df[~working_df["IsExcluded"] & working_df["SubjectLevel"].notna()]

    subject_details = (
        valid_rows[["StudentName", "SubjectName", "SubjectLevel"]]
        .drop_duplicates(subset=["StudentName", "SubjectName"])
        .reset_index(drop=True)
    )

    level_counts = (
        subject_details.groupby(["StudentName", "SubjectLevel"])
        .size()
        .unstack(fill_value=0)
    )

    subjects_by_student = (
        subject_details.groupby("StudentName")["SubjectName"]
        .apply(lambda names: sorted(set(names)))
        .to_dict()
    )

    def _totals_for(metric_key: str):
        metric_rows = valid_rows[valid_rows["metric_type"] == metric_key]
        metric_rows = metric_rows.sort_values(["StudentName", "SubjectName"])
        metric_rows = metric_rows.drop_duplicates(subset=["StudentName", "SubjectName", "metric_type"])
        return metric_rows.groupby("StudentName")["NumericValue"].sum()

    assessment_totals = _totals_for("assessment")
    flight_path_totals = _totals_for("flight_path")

    students = sorted(set(valid_rows["StudentName"].dropna()))
    rows = []
    max_subjects = 0

    for student in students:
        subjects = subjects_by_student.get(student, [])
        hl_count = level_counts.loc[student].get("HL", 0) if student in level_counts.index else 0
        sl_count = level_counts.loc[student].get("SL", 0) if student in level_counts.index else 0

        has_six_valid = len(subjects) >= 6 and hl_count >= 3 and sl_count >= 3
        subject_cells = subjects if has_six_valid else []
        max_subjects = max(max_subjects, len(subject_cells))

        rows.append(
            {
                "StudentName": student,
                "AssessmentTotal": assessment_totals.get(student, 0),
                "FlightPathTotal": flight_path_totals.get(student, 0),
                "ValidSubjects": "Y" if has_six_valid else "",
                "Subjects": subject_cells,
            }
        )

    columns = ["StudentName", "AssessmentTotal", "FlightPathTotal", "ValidSubjects"]
    columns.extend([f"Subject {idx+1}" for idx in range(max_subjects)])

    output_rows = []
    for row in rows:
        base = [
            row["StudentName"],
            row["AssessmentTotal"],
            row["FlightPathTotal"],
            row["ValidSubjects"],
        ]
        base.extend(row["Subjects"])
        base.extend(["" for _ in range(max_subjects - len(row["Subjects"]))])
        output_rows.append(base)

    return pd.DataFrame(output_rows, columns=columns)


def isams_long_to_wide_view(request):
    context = {"stage": "upload"}
    error_message = None

    if request.method == "POST":
        stage = request.POST.get("stage")

        if stage == "configure":
            uploaded_file = request.FILES.get("long_file")

            if not uploaded_file:
                error_message = "Please upload a CSV or Excel file to convert."
            else:
                try:
                    df = _read_uploaded_table(uploaded_file)
                except Exception:
                    error_message = "Unable to read the uploaded file. Please upload a valid CSV or Excel document."
                else:
                    if df.empty:
                        error_message = "The uploaded file has no data rows."
                    else:
                        request.session["isams_long_df"] = df.to_json(orient="split")

                        columns = df.columns.tolist()

                        default_rows = [col for col in ["StudentID", "StudentName"] if col in columns]
                        if not default_rows and columns:
                            default_rows = columns[:1]

                        default_col_groups = []
                        for candidate in ["SubjectName", "SubjectCode", "MetricName"]:
                            if candidate in columns and candidate not in default_col_groups:
                                default_col_groups.append(candidate)

                        if not default_col_groups and len(columns) > 1:
                            default_col_groups.append(columns[1])

                        value_column = "MetricValue" if "MetricValue" in columns else columns[-1]

                        preview_rows = df.head(5).fillna("").values.tolist()

                        context.update(
                            {
                                "stage": "configure",
                                "columns": columns,
                                "default_rows": default_rows,
                                "default_col_groups": default_col_groups,
                                "value_column": value_column,
                                "preview_rows": preview_rows,
                            }
                        )

        elif stage == "transform":
            if "isams_long_df" not in request.session:
                error_message = "Session expired. Please upload your file again."
            else:
                row_identifiers = request.POST.getlist("row_identifiers")
                column_group_1 = _clean_cell(request.POST.get("column_group_1"))
                column_group_2 = _clean_cell(request.POST.get("column_group_2"))
                value_column = _clean_cell(request.POST.get("value_column"))

                column_groups = [
                    col for col in [column_group_1, column_group_2] if col
                ]

                try:
                    df = pd.read_json(request.session["isams_long_df"], orient="split")
                except Exception:
                    error_message = "Unable to load the stored file data. Please restart the process."
                else:
                    columns = df.columns.tolist()
                    preview_rows = df.head(5).fillna("").values.tolist()

                    try:
                        wide_df = _pivot_long_to_wide(
                            df,
                            row_identifiers=row_identifiers,
                            column_groups=column_groups,
                            value_column=value_column,
                        )
                    except ValueError as exc:
                        error_message = str(exc)
                        context.update(
                            {
                                "stage": "configure",
                                "columns": columns,
                                "default_rows": row_identifiers or [],
                                "default_col_groups": column_groups or [],
                                "value_column": value_column or (columns[-1] if columns else ""),
                                "preview_rows": preview_rows,
                            }
                        )
                    else:
                        buffer = io.StringIO()
                        wide_df.to_csv(buffer, index=False)
                        buffer.seek(0)

                        response = HttpResponse(
                            buffer.getvalue(),
                            content_type="text/csv",
                        )
                        response[
                            "Content-Disposition"
                        ] = 'attachment; filename="isams_wide_table.csv"'

                        request.session.pop("isams_long_df", None)
                        return response

    if error_message:
        context["error_message"] = error_message

    return render(request, "isams_long_to_wide.html", context)


def betting_dashboard_view(request):
    return render(request, "betting_dashboard.html")
