"""The verdict line on top of a page: which state a check or a forecast gets."""

from datetime import date

from pm_agent.tracking import Forecast
from pm_agent.ui import check_verdict, forecast_verdict

DEADLINE = date(2026, 12, 18)


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
    state, text = forecast_verdict(outlook(shift=8, gap=5), DEADLINE)
    assert state == "bad" and "verpasst" in text
    assert forecast_verdict(outlook(end=None, problem="kein Tag frei"), DEADLINE)[0] == "bad"


def test_a_late_end_inside_the_deadline_is_a_warning_and_on_time_is_ok():
    assert forecast_verdict(outlook(shift=2, gap=-1), DEADLINE)[0] == "warn"
    assert forecast_verdict(outlook(shift=0, gap=0), DEADLINE)[0] == "warn"  # no buffer
    state, text = forecast_verdict(outlook(), DEADLINE)
    assert state == "ok" and text.startswith("Prognose: Voraussichtliches Ende 15.12.2026")
    assert forecast_verdict(outlook(end=None), DEADLINE) == ("ok", "Alle Aufgaben sind fertig.")


def test_a_check_says_its_first_finding_and_how_many_there_are():
    assert check_verdict(["A fehlt", "B fehlt"], ["C"], "gut") == ("bad", "2 Fehler: A fehlt …")
    assert check_verdict([], ["C zu spät"], "gut") == ("warn", "1 Warnung: C zu spät")
    assert check_verdict([], [], "Keine Fehler.") == ("ok", "Keine Fehler.")
