"""Eval harness (Phase 8).

Scores the triage processors against fixture emails with expected labels:
  - classification accuracy (category)
  - task-extraction recall (did we extract >=1 task when one was expected)
  - priority sanity (urgent/finance/meeting should outrank promotion/newsletter)

Run from repo root:  python -m evals.run_evals
Requires LLM_API_KEY (the triage LLM). Prints numeric scores.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from backend.adapters.llm import get_llm_client  # noqa: E402
from backend.services import processors  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "emails.json"
HIGH = {"urgent", "finance", "meeting", "work"}
LOW = {"promotion", "newsletter", "notification"}


def main() -> int:
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    llm = get_llm_client()

    correct = 0
    task_hits = 0
    task_expected = 0
    high_scores: list[int] = []
    low_scores: list[int] = []

    print(f"Running triage evals on {len(fixtures)} fixtures...\n")
    for fx in fixtures:
        kw = {"subject": fx["subject"], "sender": fx["sender"], "body": fx["body"]}
        cls = processors.classify(llm, **kw)
        pri = processors.prioritize(llm, **kw)
        tasks = processors.extract_tasks(llm, **kw)

        ok = cls.category == fx["expected_category"]
        correct += int(ok)
        if fx.get("expect_task"):
            task_expected += 1
            task_hits += int(len(tasks) >= 1)
        (high_scores if fx["expected_category"] in HIGH else
         low_scores if fx["expected_category"] in LOW else []).append(pri.score)

        mark = "OK " if ok else "XX "
        print(f"  {mark} {fx['expected_category']:<12} -> {cls.category:<12} "
              f"(conf {cls.confidence:.2f}, prio {pri.score:>3}, tasks {len(tasks)})")

    n = len(fixtures)
    acc = correct / n if n else 0.0
    task_recall = (task_hits / task_expected) if task_expected else 1.0
    avg_high = sum(high_scores) / len(high_scores) if high_scores else 0
    avg_low = sum(low_scores) / len(low_scores) if low_scores else 0

    print("\n=== SCORES ===")
    print(f"Classification accuracy : {acc:.0%}  ({correct}/{n})")
    print(f"Task-extraction recall  : {task_recall:.0%}  ({task_hits}/{task_expected})")
    print(f"Avg priority (important): {avg_high:.0f}")
    print(f"Avg priority (low-value): {avg_low:.0f}")
    print(f"Priority separation OK  : {avg_high > avg_low}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
