"""What the model is asked, and what is done with its answer.

Four tasks, one shape: the app gathers the facts (`*_facts`, the same
analysis functions as the pages), the model reads them and answers in a
fixed JSON schema, and the app checks the answer before anything reaches
the screen -- a category that does not exist, a number that was not in the
facts, an action the plan would refuse: dropped, with the reason.

- `suggest_merchants`: a category for the payees no rule recognises;
- `review_summary`: the month's review in three sentences;
- `explain_month`: why a month cost more (or less) than usual;
- `plan_question` / `answer_question`: a question in French becomes a query
  the app runs (`run_query`), then a sentence about its result.

The scenario-in-words task lives with the plan's own actions, in
`web/api/assist/scenario.py`, because it ends in `apply_plan_action`.

One module per task (`merchants`, `month`, `savings`, `questions`), what
they share in `common`; the names the rest of the app uses are here.
"""

from .common import LANG, NUMBERS, _Names, _ask_checked, _hash, fold, period_facts  # noqa: F401
from .merchants import COMPANY, search_query, suggest_merchants, uncategorised_payees  # noqa: F401
from .month import explain_month, month_facts, review_facts, review_memo_key, review_summary  # noqa: F401
from .savings import explain_savings, savings_facts  # noqa: F401
from .questions import FOCUS, FOCUS_SOURCES, FOCUS_TITLE, answer_question, forecast_facts, plan_question, run_query  # noqa: F401
