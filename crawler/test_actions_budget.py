"""Vakt for GitHub Actions-minutter.

Repoet skal kunne gjøres privat. GitHub Free gir da 2000 minutter per måned, og hver jobb
rundes opp til hele minutter. Testen regner verste tilfelle for planlagte kjøringer
(antall kjøringer per måned × timeout-minutes) og feiler hvis summen overstiger budsjettet.
Resten (quality.yml ved push og manuelle kjøringer) har en reserve på 300 minutter.
"""
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
MONTHLY_FREE_MINUTES = 2000
RESERVE_FOR_PUSH_AND_MANUAL = 300
SCHEDULED_BUDGET = MONTHLY_FREE_MINUTES - RESERVE_FOR_PUSH_AND_MANUAL
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


class ActionsBudgetTest(unittest.TestCase):
    def test_cron_parser(self):
        self.assertEqual(runs_per_month("17 */4 * * *"), 6 * 31)
        self.assertEqual(runs_per_month("43 5 * * *"), 31)
        self.assertEqual(runs_per_month("0,30 */2 * * *"), 24 * 31)

    def test_scheduled_workflows_fit_private_free_tier(self):
        usage = {p.name: scheduled_minutes(p.read_text()) for p in sorted(WORKFLOWS.glob("*.y*ml"))}
        total = sum(usage.values())
        self.assertLessEqual(
            total,
            SCHEDULED_BUDGET,
            f"Planlagte workflows kan bruke {total} min/mnd i verste fall {usage}, "
            f"budsjett {SCHEDULED_BUDGET} (privat repo: {MONTHLY_FREE_MINUTES} gratis).",
        )

    def test_every_job_has_timeout(self):
        for path in WORKFLOWS.glob("*.y*ml"):
            text = path.read_text()
            jobs = len(re.findall(r"runs-on:", text))
            self.assertEqual(jobs, len(re.findall(r"timeout-minutes:", text)), f"{path.name}: alle jobber trenger timeout-minutes")


if __name__ == "__main__":
    unittest.main()
