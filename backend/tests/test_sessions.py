from datetime import date

from app.services.acquisition.sessions import expected_windows, parse_cohorts, parse_session, session_label


def test_parse_session_prefers_scheme_marked_session():
    title = "B.Tech Degree S3 (S,FE) / S1 (PT)(S) June 2024 (2019 Scheme)/S3 (WP)(R) December 2023 Examination"
    assert parse_session(title) == (6, 2024)


def test_parse_session_variants():
    assert parse_session("Third Semester B.Tech Degree Examination December 2020 (2019 Scheme)") == (12, 2020)
    assert parse_session("MAT201 ..., NOVEMBER 2024") == (11, 2024)
    assert parse_session("December 2022 Regular") == (12, 2022)
    assert parse_session("Dec-2021") == (12, 2021)
    assert parse_session("no session here") is None


def test_parse_cohorts():
    assert parse_cohorts("B.Tech Degree S3 (R,S) / S1 (PT) (S,FE) Examination") == ["S3 (R,S)", "S1 (PT)(S,FE)"]
    assert parse_cohorts("Third Semester B.Tech Degree Regular and Supplementary Examination") == ["Regular+Supplementary"]


def test_expected_windows_mat201():
    ws = expected_windows(2020, 12, today=date(2026, 10, 8))
    labels = [w.label for w in ws]
    assert labels[0] == "Nov/Dec 2020 regular"
    assert "May/Jun 2020 supplementary" not in labels  # before the first exam
    assert "May/Jun 2026 supplementary" in labels
    assert "Nov/Dec 2026 regular" not in labels  # not held yet
    assert len([w for w in ws if w.kind == "regular"]) == 6  # 2020..2025
    reg2024 = next(w for w in ws if w.label == "Nov/Dec 2024 regular")
    assert reg2024.contains(11, 2024) and reg2024.contains(1, 2025) and not reg2024.contains(6, 2024)
    assert session_label(6, 2024) == "June 2024"
