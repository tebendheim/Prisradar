"""Vakt for GitHub Actions-minutter.

Repoet skal kunne gjøres privat. GitHub Free gir da 2000 minutter per måned, og hver jobb
rundes opp til hele minutter. Testen regner verste tilfelle for planlagte kjøringer
(antall kjøringer per måned × timeout-minutes) pluss manuelle kjøringer, som leses fra
kommentarlinjen `-- actions-budget: manual_runs_per_30d=N minutes_per_run=M` i den høyeste
migreringsfilen som har den. Summen må være maks 1760 min/mnd, slik at 240 min er igjen til
quality.yml ved push.
"""
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
MONTHLY_FREE_MINUTES = 2000
RESERVE_FOR_QUALITY_PUSH = 240
SCHEDULED_AND_MANUAL_BUDGET = MONTHLY_FREE_MINUTES - RESERVE_FOR_QUALITY_PUSH  # 1760
MIGRATIONS = WORKFLOWS.parent.parent / "supabase" / "migrations"
DAYS_PER_MONTH = 31


def expand(field, lo, hi):
    values = set()
    for part in field.split(","):
        rng, _, step = part.partition("/")
        step = int(step) if step else 1
        if rng == "*":
            start, end = lo, hi
        elif "-" in rng:
            start, end = (int(x) for x in rng.split("-"))
        else:
            start = int(rng)
            end = hi if step > 1 else start
        values.update(range(start, end + 1, step))
    return values


def runs_per_month(cron):
    minute, hour, dom, month, dow = cron.split()
    per_day = len(expand(minute, 0, 59)) * len(expand(hour, 0, 23))
    if dom == "*" and dow == "*":
        return per_day * DAYS_PER_MONTH
    days = len(expand(dom, 1, 31)) if dom != "*" else DAYS_PER_MONTH
    if dow != "*":
        days = min(DAYS_PER_MONTH, max(days if dom != "*" else 0, len(expand(dow, 0, 6)) * 5))
    return per_day * days


def scheduled_minutes(text):
    crons = re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", text)
    timeouts = [int(t) for t in re.findall(r"timeout-minutes:\s*(\d+)", text)]
    if not crons:
        return 0
    if not timeouts:
        raise AssertionError("Planlagt workflow mangler timeout-minutes")
    # Alle jobber i workflowen kjører ved hver trigger.
    return sum(runs_per_month(c) for c in crons) * sum(timeouts)


def manual_minutes():
    for path in sorted(MIGRATIONS.glob("*.sql"), reverse=True):
        m = re.search(r"^--\s*actions-budget:\s*manual_runs_per_30d=(\d+)\s+minutes_per_run=(\d+)\s*$", path.read_text(), re.M)
        if m:
            return int(m[1]) * int(m[2])
    raise AssertionError("Ingen migrering har kommentarlinjen '-- actions-budget: manual_runs_per_30d=N minutes_per_run=M'")


class ActionsBudgetTest(unittest.TestCase):
    def test_cron_parser(self):
        self.assertEqual(runs_per_month("17 */4 * * *"), 6 * 31)
        self.assertEqual(runs_per_month("43 5 * * *"), 31)
        self.assertEqual(runs_per_month("0,30 */2 * * *"), 24 * 31)

    def test_scheduled_plus_manual_fit_private_free_tier(self):
        usage = {p.name: scheduled_minutes(p.read_text()) for p in sorted(WORKFLOWS.glob("*.y*ml"))}
        scheduled = sum(usage.values())
        manual = manual_minutes()
        self.assertLessEqual(
            scheduled + manual,
            SCHEDULED_AND_MANUAL_BUDGET,
            f"Planlagt {scheduled} {usage} + manuelt {manual} min/mnd i verste fall, "
            f"budsjett {SCHEDULED_AND_MANUAL_BUDGET} (privat repo: {MONTHLY_FREE_MINUTES} gratis, "
            f"{RESERVE_FOR_QUALITY_PUSH} reservert til quality.yml).",
        )

    def test_every_job_has_timeout(self):
        for path in WORKFLOWS.glob("*.y*ml"):
            text = path.read_text()
            jobs = len(re.findall(r"runs-on:", text))
            self.assertEqual(jobs, len(re.findall(r"timeout-minutes:", text)), f"{path.name}: alle jobber trenger timeout-minutes")


if __name__ == "__main__":
    unittest.main()
