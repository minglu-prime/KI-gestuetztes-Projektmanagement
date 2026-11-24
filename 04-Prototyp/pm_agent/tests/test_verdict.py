"""The verdict line on top of a page: which state a check or a forecast gets."""

from datetime import date
from types import SimpleNamespace

from pm_agent.tracking import Forecast
from pm_agent.ui import check_verdict, forecast_verdict, next_open

DEADLINE = date(2026, 12, 18)


def effort(earned=8.0, over=0.0):
    """The two numbers of an Evaluation the verdict reads."""
    return SimpleNamespace(earned=earned, finished_deviation=over)


ON_PLAN = effort()


def outlook(shift=0, gap=-3, end=date(2026, 12, 15), problem=None):
    return Forecast(
        planned_end=date(2026, 12, 15),
        end=end,
        shift=shift,
        deadline_gap=gap,
        blocked={},
        schedule=[],
        problem=problem,
    )


def test_a_missed_deadline_or_no_forecast_is_bad():
    state, text = forecast_verdict(outlook(shift=8, gap=5), DEADLINE, ON_PLAN)
    assert state == "bad" and "verpasst" in text
    assert (
        forecast_verdict(outlook(end=None, problem="kein Tag frei"), DEADLINE, ON_PLAN)[0] == "bad"
    )


def test_a_late_end_inside_the_deadline_is_a_warning_and_on_time_is_ok():
    assert forecast_verdict(outlook(shift=2, gap=-1), DEADLINE, ON_PLAN)[0] == "warn"
    assert forecast_verdict(outlook(shift=0, gap=0), DEADLINE, ON_PLAN)[0] == "warn"  # no buffer
    state, text = forecast_verdict(outlook(), DEADLINE, ON_PLAN)
    assert state == "ok" and text.startswith("Prognose: Voraussichtliches Ende 15.12.2026")
    assert forecast_verdict(outlook(end=None), DEADLINE, ON_PLAN) == (
        "ok",
        "Alle Aufgaben sind fertig.",
    )


def test_finished_work_over_its_hours_asks_for_a_decision():
    state, text = forecast_verdict(outlook(), DEADLINE, effort(earned=8, over=2))
    assert state == "warn"
    assert text.endswith("Fertige Aufgaben brauchten 25 % mehr Stunden als geplant (+2 h).")
    assert forecast_verdict(outlook(), DEADLINE, effort(earned=10, over=1))[0] == "ok"  # 10 %
    assert forecast_verdict(outlook(shift=8, gap=5), DEADLINE, effort(over=4))[0] == "bad"
    assert forecast_verdict(outlook(), DEADLINE, effort(earned=0, over=0))[0] == "ok"
    state, text = forecast_verdict(outlook(end=None), DEADLINE, effort(earned=8, over=4))
    assert state == "warn" and text.startswith("Alle Aufgaben sind fertig. Fertige")


def test_a_check_says_its_first_finding_and_how_many_there_are():
    assert check_verdict(["A fehlt", "B fehlt"], ["C"], "gut") == ("bad", "2 Fehler: A fehlt …")
    assert check_verdict([], ["C zu spät"], "gut") == ("warn", "1 Warnung: C zu spät")
    assert check_verdict([], [], "Keine Fehler.") == ("ok", "Keine Fehler.")


def test_the_next_open_entry_comes_after_the_current_one_and_wraps():
    order = ["T1", "T2", "T3", "T4"]
    assert next_open(order, {"T1", "T2"}, "T2") == "T3"
    assert next_open(order, {"T3", "T4"}, "T4") == "T1"  # from the start again
    assert next_open(order, set(order), "T2") == "T2"  # all done: stays
    assert next_open(order, set(), "T9") == "T1"  # unknown: the first open one
