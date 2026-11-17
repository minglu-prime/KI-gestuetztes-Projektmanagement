"""The day each task was finished, and the actual end in the closing report."""

from datetime import date, datetime

import pandas as pd
import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent import closing
from pm_agent.models import Plan
from pm_agent.tracking import (
    Defect,
    Progress,
    adopt,
    apply_rows,
    evaluate,
    progress_rows,
    record_defect,
    reopen,
    rest_project,
)
from pm_agent.workbench import InputError

# A (8 h) is planned for Mon 09.11.2026, B (16 h) for 10.–11.11.2026.
PLAN = Plan.model_validate(plan_input())
MON, TUE, WED, FRI = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 13)


@pytest.fixture
def tracking(tmp_path):
    return adopt(PROJECT, TEAM, PLAN, path=tmp_path / "projekt.json")


def test_progress_saved_before_finish_dates_existed_still_loads():
    assert Progress.model_validate({"status": "fertig"}).finished_on is None


def test_finishing_a_task_records_the_day_and_saving_again_keeps_it(tracking):
    done = apply_rows(tracking, [{"ID": "A", "Status": "fertig"}], today=TUE)
    assert done.progress["A"].finished_on == TUE
    again = apply_rows(done, progress_rows(done, today=FRI), today=FRI)
    assert again.progress["A"].finished_on == TUE


def test_a_task_no_longer_finished_loses_its_date(tracking):
    done = apply_rows(tracking, [{"ID": "A", "Status": "fertig"}], today=TUE)
    rows = progress_rows(done, today=WED)
    rows[0]["Status"] = "in Arbeit"  # the date cell still shows 10.11.
    back = apply_rows(done, rows, today=WED)
    assert back.progress["A"].finished_on is None


def test_the_lead_can_enter_the_day_a_task_was_finished(tracking):
    for cell in [MON, datetime(2026, 11, 9), "09.11.2026", "2026-11-09"]:
        done = apply_rows(tracking, [{"ID": "A", "Status": "fertig", "Fertig am": cell}], FRI)
        assert done.progress["A"].finished_on == MON


@pytest.mark.parametrize("empty", [None, float("nan"), pd.NaT, ""])
def test_an_emptied_date_of_a_finished_task_means_unknown(tracking, empty):
    done = apply_rows(tracking, [{"ID": "A", "Status": "fertig"}], today=TUE)
    cleared = apply_rows(done, [{"ID": "A", "Status": "fertig", "Fertig am": empty}], WED)
    assert cleared.progress["A"].finished_on is None


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            {"ID": "A", "Status": "fertig", "Fertig am": date(2026, 11, 14)},
            r"Zeile 1 \(A\): Fertig am 14.11.2026 liegt in der Zukunft",
        ),
        (
            {"ID": "A", "Status": "fertig", "Fertig am": date(2026, 11, 6)},
            r"Zeile 1 \(A\): Fertig am 06.11.2026 liegt vor dem Projektstart 09.11.2026",
        ),
        (
            {"ID": "A", "Status": "fertig", "Fertig am": "gestern"},
            r"Zeile 1 \(A\): Fertig am 'gestern' ist kein Datum",
        ),
        (
            {"ID": "A", "Status": "in Arbeit", "Fertig am": MON},
            r"Zeile 1 \(A\): Fertig am gesetzt, aber Status 'in Arbeit'",
        ),
    ],
)
def test_an_impossible_finish_date_names_the_row_and_the_problem(tracking, row, message):
    with pytest.raises(InputError, match=message):
        apply_rows(tracking, [row], today=FRI)


def test_the_progress_table_shows_the_day_instead_of_a_forecast(tracking):
    done = apply_rows(tracking, [{"ID": "A", "Status": "fertig"}], today=TUE)
    row = progress_rows(done, today=FRI)[0]
    assert row["Fertig am"] == TUE
    assert row["Prognose Ende"] == "fertig am 10.11.2026"
    assert progress_rows(done, today=FRI)[1]["Fertig am"] is None


def test_a_reopened_task_loses_its_date(tracking):
    done = apply_rows(tracking, [{"ID": "B", "Status": "fertig"}], today=WED)
    defect = record_defect(done, Defect(case_id="T2", severity="mittel", cause="x", task_id="B"))
    assert reopen(defect, "F1").progress["B"].finished_on is None


def test_the_date_goes_into_the_history_when_the_rest_is_adopted_again(tracking, tmp_path):
    done = apply_rows(tracking, [{"ID": "A", "Status": "fertig"}], today=TUE)
    project, rest = rest_project(done, TUE)
    again = adopt(project, TEAM, rest, path=tmp_path / "neu.json", keep=done)
    assert [e.finished_on for e in again.history] == [TUE]


def report(tracking, today=FRI):
    return closing.closing_document(tracking, None, evaluate(tracking, today))


def test_the_report_names_the_actual_end_and_how_far_it_is_from_the_plan(tracking):
    done = apply_rows(tracking, [{"ID": "A", "Status": "fertig", "Fertig am": MON}], FRI)
    done = apply_rows(done, [{"ID": "B", "Status": "fertig", "Fertig am": FRI}], FRI)
    text = report(done)
    assert "**Tatsächliches Ende:** 13.11.2026 (2 Arbeitstage nach Plan)" in text
    assert "| B | " in text and "| 11.11.2026 | 13.11.2026 | 2 |" in text
    assert "| A | " not in text.split("## Später fertig als geplant")[1].split("##")[0]


def test_on_time_the_report_says_so(tracking):
    done = apply_rows(tracking, [{"ID": "A", "Status": "fertig", "Fertig am": MON}], FRI)
    done = apply_rows(done, [{"ID": "B", "Status": "fertig", "Fertig am": TUE}], FRI)
    text = report(done)
    assert "**Tatsächliches Ende:** 10.11.2026 (1 Arbeitstag vor Plan)" in text
    assert "Keine Aufgabe wurde später fertig als geplant." in text


def test_with_open_tasks_the_end_is_still_open(tracking):
    done = apply_rows(tracking, [{"ID": "A", "Status": "fertig"}], today=TUE)
    assert "**Tatsächliches Ende:** noch offen (1 von 2 Aufgaben fertig)" in report(done)


def test_finished_tasks_without_a_date_make_the_end_a_lower_bound(tracking):
    done = apply_rows(tracking, [{"ID": "A", "Status": "fertig", "Fertig am": MON}], FRI)
    old = done.model_copy(
        update={"progress": {**done.progress, "B": Progress(status="fertig", actual_hours=16)}}
    )
    text = report(old)
    assert "**Tatsächliches Ende:** 09.11.2026 (2 Arbeitstage vor Plan)" in text
    assert "1 fertige Aufgabe ohne Fertigdatum" in text
    nothing = old.model_copy(
        update={"progress": {k: Progress(status="fertig") for k in old.progress}}
    )
    assert "**Tatsächliches Ende:** unbekannt (keine Fertigdaten erfasst)" in report(nothing)


def test_a_task_finished_late_under_an_earlier_plan_is_in_the_late_table(tracking, tmp_path):
    # A planned for Mon 09.11., finished Wed 11.11.; the rest (B) adopted again on Thu.
    late = apply_rows(tracking, [{"ID": "A", "Status": "fertig", "Fertig am": WED}], WED)
    project, rest = rest_project(late, date(2026, 11, 12))
    again = adopt(project, TEAM, rest, path=tmp_path / "neu.json", keep=late)
    assert again.history[0].planned_end == MON
    done = apply_rows(again, [{"ID": "B", "Status": "fertig"}], today=FRI)
    text = report(done)
    assert "| A | " in text and "| 09.11.2026 | 11.11.2026 | 2 |" in text


def test_tasks_without_a_date_keep_the_late_table_from_claiming_none_was_late(tracking):
    old = tracking.model_copy(
        update={"progress": {k: Progress(status="fertig") for k in tracking.progress}}
    )
    text = report(old)
    assert "Keine Aufgabe wurde später fertig als geplant." not in text
    assert "Von 2 fertigen Aufgaben ohne Fertigdatum ist unbekannt" in text
