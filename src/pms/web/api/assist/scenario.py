"""D. A sentence becomes changes to the plan, shown before they are saved;
a cash floor becomes what keeps the plan above it, priced lever by lever."""

from __future__ import annotations

import json
import math

from flask import request
from werkzeug.datastructures import MultiDict

from .... import ai, analysis, assist
from .... import plans as plans_module
from ...views.previsions import _plan, _wealth, apply_plan_action, months_ahead, months_label
from .. import api, payload, store
from . import _body, _config, _failed


# --- D. a scenario in words -----------------------------------------------------

SCENARIO_SCHEMA = ai.strict({"type": "object", "properties": {
    "supported": {"type": "boolean"},
    "name": {"type": "string"},
    "note": {"type": "string"},
    "floor": {"type": ["number", "null"]},
    "changes": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["contrib", "add", "income", "spend"]},
        "amount": {"type": "number"},
        "pocket": {"type": ["string", "null"], "enum": ["3a", "taxable", None]},
        "every": {"type": ["string", "null"],
                  "enum": [*plans_module.CONTRIBUTION_EVERY, None]},
        "months": {"type": ["integer", "null"]},
        "start": {"type": ["string", "null"]},
        "label": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"]},
        "month": {"type": ["string", "null"]},
        "destination": {"type": ["string", "null"], "enum": ["", "3a", "taxable", None]},
    }}},
}})
CHANGE_FIELDS = ("amount", "pocket", "every", "months", "start", "label", "date",
                 "month", "destination")


def _describe(change: dict) -> str:
    """One change as the page states it -- written by the app, not the
    model, from the very fields that will be applied."""
    amount = analysis.chf(float(change.get("amount") or 0))
    action = change["action"]
    if action == "contrib-del":
        return f"Versement de {amount} CHF retiré du plan"
    if action == "amount":
        return f"Ponctuel « {change.get('label')} » ramené à {amount} CHF"
    if action == "delete":
        return f"Ponctuel « {change.get('label')} » retiré du plan"
    if action == "contrib":
        pocket = "le 3a" if change.get("pocket") == "3a" else "le placement"
        start = plans_module.month_label(change["start"]) if change.get("start") else "le mois prochain"
        months = int(change.get("months") or 0)
        return (f"Versement de {amount} CHF {plans_module.CONTRIBUTION_LABELS.get(change.get('every') or '', '')}"
                f" sur {pocket}, dès {start}, pendant {months_label(months)}")
    if action == "add":
        when = change.get("date") or change.get("month") or ""
        return f"Ponctuel « {change.get('label') or ''} » de {amount} CHF ({when})"
    if action == "income":
        return f"Revenu mensuel déclaré : {amount} CHF"
    return f"Dépense mensuelle habituelle déclarée : {amount} CHF"


def _floor_changes(data, plan: plans_module.Plan, horizon: int, floor: float,
                   lever: str | None = None) -> tuple[list[dict], str, list[dict], str | None]:
    """A cash floor is not a line of the plan; what keeps the plan above it
    is. With room: the most that can go to the investment pocket each month.
    Short: every way of holding it with one lever, priced -- each declared
    transfer, the monthly spend, each one-off ahead -- so they compare side
    by side ("verser 400 au lieu de 500", "« Voyage » : 2'850 au lieu de
    4'000"); one is applied, `lever` or the first that suffices. A first
    version offered the levers as bare chips and priced only the one
    clicked: the page read as a wall of buttons. Every amount is checked on
    the projection itself, changes applied: a formula assumed the change ran
    from this month, and a transfer starting in January left the first
    proposal more than a thousand francs under the floor.

    Returns (changes, note, options, the option applied)."""
    statement = data.statement
    floor_text = analysis.chf(floor, 0)
    start = plans_module.month_key(plans_module._add_months(statement.period_end, 1))
    projection = plans_module.project(statement, plan, months_ahead=horizon)
    base_path = [r["end"] for r in projection["rows"]]

    def path(changes: list[dict] | None) -> dict | None:
        if changes is None:
            return None
        copy = plans_module._detached(plan._declarations(), plan.installments)
        if _apply_changes(copy, changes):
            return None
        return plans_module.project(statement, copy, months_ahead=horizon)

    def holds(projected: dict | None) -> bool:
        return projected is not None and projected["low"]["amount"] >= floor - 0.005

    if projection["cash"] < floor:
        return [], (f"Le cash est déjà sous {floor_text} CHF aujourd'hui "
                    f"({analysis.chf(projection['cash'], 0)}) : aucun changement du plan n'y remédie."), [], None
    tightest = projection["low"]["label"]

    def bisect(build, top: int, want_max: bool) -> int | None:
        """The largest (want_max) or smallest ten-franc step for which
        `build(x)` holds the floor, between 0 and `top` francs."""
        lo, hi = 0, max(top, 0) // 10
        if want_max:
            if not holds(path(build(10))):
                return 0
            lo = 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                lo, hi = (mid, hi) if holds(path(build(mid * 10))) else (lo, mid - 1)
            return lo * 10
        if hi == 0 or not holds(path(build(hi * 10))):
            return None
        while lo < hi:
            mid = (lo + hi) // 2
            lo, hi = (lo, mid) if holds(path(build(mid * 10))) else (mid + 1, hi)
        return lo * 10

    def solve(build, top: int) -> int | None:
        """The least cut that holds. The cash moves in proportion to the cut,
        so the far end's curve says where each franc lands; the estimate is
        then checked, and adjusted by ten francs, on the projection -- a
        handful of projections per lever instead of a dozen."""
        top = max(top, 0) // 10 * 10
        if top <= 0:
            return None
        far = path(build(top))
        if not holds(far):
            return None
        need = 0.0
        for before, after in zip(base_path, (r["end"] for r in far["rows"])):
            if before < floor - 0.005:
                per_franc = (after - before) / top
                if per_franc <= 1e-9:
                    return bisect(build, top, want_max=False)
                need = max(need, (floor - before) / per_franc)
        x = min(top, max(10, math.ceil(need / 10 - 1e-9) * 10))
        for _ in range(3):
            if holds(path(build(x))):
                break
            x = min(top, x + 10)
        else:
            return bisect(build, top, want_max=False)
        for _ in range(3):
            if x <= 10 or not holds(path(build(x - 10))):
                break
            x -= 10
        return x

    if projection["low"]["amount"] >= floor:
        def more(x):
            return [{"action": "contrib", "pocket": plans_module.TAXABLE, "amount": x,
                     "every": "month", "months": 480, "start": start}]
        x = bisect(more, 200_000, want_max=True)
        if not x:
            return [], (f"Le plan tient déjà juste au-dessus de {floor_text} CHF : aucune marge "
                        f"à placer chaque mois ({tightest} est le mois le plus serré)."), [], None
        return more(x), (f"Le plan reste au-dessus de {floor_text} CHF avec {analysis.chf(x, 0)} CHF de "
                         f"plus versés chaque mois au placement ; {tightest} est le mois le plus serré."), [], None

    baseline = projection["baseline"]
    every = plans_module.CONTRIBUTION_LABELS
    money = lambda v: analysis.chf(v, 0)  # noqa: E731

    def cut_contrib(c, x):
        cut = min(c["amount"], x)
        out = [{"action": "contrib-del", **{k: c[k] for k in ("pocket", "amount", "every", "months")},
                "start": c.get("start", "")}]
        if c["amount"] - cut > 0:
            out.append({"action": "contrib", "pocket": c["pocket"], "amount": round(c["amount"] - cut, 2),
                        "every": c["every"], "months": c["months"], "start": c.get("start") or start})
        return out, cut

    def spend_less(x):
        return [{"action": "spend", "amount": round(baseline - x, 2)}] if x < baseline else None

    # (id, label, build, top, before, how the option reads once priced)
    levers = []
    for i, c in sorted(enumerate(plan.contributions), key=lambda ic: -ic[1]["amount"]):
        pocket = "3a" if c["pocket"] == plans_module.SHELTERED else "placement"
        per = every.get(c["every"], "")

        def text(after, before, pocket=pocket, per=per):
            if after <= 0:
                return f"Suspendre le versement {pocket} ({money(before)} {per})"
            return f"Verser {money(after)} au lieu de {money(before)} {per} au {pocket}"
        levers.append((f"contrib:{i}", f"Versement {pocket}",
                       lambda x, c=c: cut_contrib(c, x)[0] if x <= c["amount"] else None,
                       int(c["amount"]), c["amount"], text, c["every"]))
    levers.append(("spend", "Dépense mensuelle", spend_less, int(baseline) - 10, baseline,
                   lambda after, before: f"Dépenser {money(after)} au lieu de {money(before)} par mois",
                   "month"))
    ahead = {r["key"] for r in projection["rows"]}
    for e in plan.one_offs:
        if e["month"] not in ahead or e.get("transfer"):
            continue
        when = plans_module.month_label(e["month"])

        def text(after, before, label=e["label"], when=when):
            if after <= 0:
                return f"Renoncer à « {label} » ({money(before)}, {when})"
            return f"« {label} » : {money(after)} au lieu de {money(before)} ({when})"
        levers.append((f"oneoff:{e['month']}|{e['label']}", e["label"],
                       lambda x, e=e: (None if x > e["amount"] else
                                       [{"action": "delete", "month": e["month"], "label": e["label"]}]
                                       if e["amount"] - x < 0.005 else
                                       [{"action": "amount", "month": e["month"], "label": e["label"],
                                         "amount": round(e["amount"] - x, 2)}]),
                       int(e["amount"]), e["amount"], text, None))

    per_unit = {"month": " par mois", "quarter": " par trimestre", "semester": " par semestre",
                "year": " par an"}
    options, builds = [], {}
    for id_, label, build, top, before, text, unit in levers:
        x = solve(build, top)
        builds[id_] = (build, x)
        options.append({"id": id_, "label": label, "feasible": x is not None,
                        "cut": x, "unit": unit, "before": round(before, 2),
                        "text": text(before - x, before) if x is not None else label,
                        "cost": f"−{money(x)}{per_unit.get(unit or '', '')}" if x is not None else None})
    # Monthly levers first, as declared; the one-offs by the share they give up.
    monthly = [o for o in options if not o["id"].startswith("oneoff:")]
    once = sorted((o for o in options if o["id"].startswith("oneoff:")),
                  key=lambda o: (not o["feasible"], (o["cut"] or 0) / (o["before"] or 1)))
    options = monthly + once

    if not any(o["feasible"] for o in options):
        # No single lever holds: the largest monthly transfer, then the spend.
        monthly_c = [c for c in plan.contributions if c["every"] == "month"]
        c = max(monthly_c, key=lambda c: c["amount"]) if monthly_c else None

        def both(x):
            changes, left = [], float(x)
            if c is not None:
                part, cut = cut_contrib(c, left)
                changes += part
                left -= cut
            if left > 0:
                rest = spend_less(left)
                if rest is None:
                    return None
                changes += rest
            return changes
        x = solve(both, int((c["amount"] if c else 0) + baseline) - 10)
        if x is None:
            return [], (f"Un plancher de {floor_text} CHF n'est pas tenable avec ce plan : même sans "
                        f"versement mensuel et avec une dépense presque nulle, le cash passe dessous "
                        f"({tightest} est le mois le plus serré)."), options, None
        options.insert(0, {"id": "auto", "label": "Les deux", "feasible": True, "cut": x, "unit": "month",
                           "before": None, "cost": f"−{money(x)} par mois",
                           "text": "Aucun levier ne suffit seul : réduire le plus gros versement "
                                   "mensuel, puis la dépense pour le reste"})
        builds["auto"] = (both, x)

    chosen = lever if lever in builds and builds[lever][1] is not None \
        else next(o["id"] for o in options if o["feasible"])
    build, x = builds[chosen]
    gap = floor - projection["low"]["amount"]
    note = (f"Avec le plan actuel, le cash descend à {money(projection['low']['amount'])} CHF en "
            f"{tightest}, {money(gap)} sous ton plancher de {floor_text}. "
            + ("Aucun levier ne suffit seul." if "auto" in builds else
               "Chacune de ces options suffit seule, vérifiée sur la projection :"))
    return build(x), note, options, chosen


def _diff_rows(change: dict, plan: plans_module.Plan) -> list[dict]:
    """The change as the lines of a diff: the line added, then what it
    rests on -- written by the app from the fields that will be applied."""
    amount = float(change.get("amount") or 0)
    action = change["action"]
    if action == "contrib-del":
        pocket = "le 3a" if change.get("pocket") == "3a" else "le placement"
        every = plans_module.CONTRIBUTION_LABELS.get(change.get("every") or "", "")
        return [{"label": f"− Versement {every} vers {pocket}", "value": amount, "remove": True}]
    if action == "delete":
        before = next((e["amount"] for e in plan.one_offs
                       if e["month"] == change.get("month") and e["label"] == change.get("label")), "")
        return [{"label": f"− {change.get('label')} ({plans_module.month_label(change['month'])})",
                 "value": before, "remove": True}]
    if action == "amount":
        before = next((e["amount"] for e in plan.one_offs
                       if e["month"] == change.get("month") and e["label"] == change.get("label")), None)
        return [{"label": f"− {change.get('label')} ({plans_module.month_label(change['month'])})",
                 "value": before if before is not None else "", "remove": True},
                {"label": f"+ {change.get('label')}, réduit", "value": amount, "add": True}]
    if action == "contrib":
        pocket = "le 3a" if change.get("pocket") == "3a" else "le placement"
        every = plans_module.CONTRIBUTION_LABELS.get(change.get("every") or "", "")
        months = int(change.get("months") or 0)
        rate = (plan.rate_segments[0][1] if plan.rate_segments else plan.rate)
        barème = (plans_module.scenario_summary(plan.rate_segments, plan.vol).split(" · ")[0]
                  if plan.rate_segments else None)
        return [
            {"label": f"+ Versement {every} vers {pocket}", "value": amount, "add": True},
            {"label": "Début", "value": plans_module.month_label(change["start"])
             if change.get("start") else "le mois prochain"},
            {"label": "Durée", "value": "sans fin" if months >= 480 else months_label(months)},
            {"label": "Rendement", "value": f"celui du plan : {barème}" if barème
             else f"celui du plan ({rate * 100:g} %)" if rate is not None else "aucun déclaré"},
        ]
    if action == "add":
        rows = [{"label": f"+ {change.get('label') or 'Ponctuel'}", "value": amount, "add": True},
                {"label": "Quand", "value": change.get("date") or change.get("month") or ""}]
        if change.get("destination"):
            rows.append({"label": "Vers", "value": plans_module.DESTINATION_LABELS.get(
                change["destination"], change["destination"])})
        return rows
    label = "Revenu mensuel" if action == "income" else "Dépense mensuelle habituelle"
    current = plan.income if action == "income" else plan.spend
    return [{"label": label, "value": amount, "add": True},
            {"label": "Avant", "value": current if current is not None else "médiane de l'historique"}]


def _apply_changes(plan: plans_module.Plan, changes: list[dict]) -> list[str]:
    """Each change through the plan's own form handling; the messages of
    whatever it refuses."""
    problems = []
    for change in changes:
        form = MultiDict({"action": change["action"]})
        for field in CHANGE_FIELDS:
            value = change.get(field)
            if value not in (None, ""):
                form[field] = str(value)
        errors, _, _ = apply_plan_action(plan, form, months_ahead(request.args))
        problems += [f"{_describe(change)} : {m}" for m in errors.values()]
    return problems


def _clean(changes) -> list[dict]:
    """Changes posted back by the page: only the known fields, typed."""
    out = []
    for c in changes if isinstance(changes, list) else []:
        if isinstance(c, dict) and c.get("action") in ("contrib", "contrib-del", "amount", "delete", "add", "income", "spend"):
            out.append({"action": c["action"],
                        **{f: c.get(f) for f in CHANGE_FIELDS if c.get(f) not in (None, "")}})
    return out


def _projection(data, plan: plans_module.Plan, horizon: int) -> dict:
    projection = plans_module.project(data.statement, plan, months_ahead=horizon)
    wealth, _ = _wealth(data, plan, projection)
    rows = projection["rows"]
    return {"low": projection["low"], "end": rows[-1]["end"] if rows else projection["cash"],
            "cash": [{"label": r["label"], "key": r["key"], "value": r["end"]} for r in rows],
            "wealth": [{"label": r["label"], "key": rr["key"], "value": r["total"]}
                       for r, rr in zip(wealth["rows"], rows)] if wealth else None,
            "wealth_final": wealth["final"]["total"] if wealth and wealth["final"] else None}


@api.route("/api/ai/scenario", methods=["POST"])
def ai_scenario():
    """`preview`: the sentence becomes changes, applied to a copy of the
    live plan and projected next to it. `save`: those changes, as posted
    back, kept as a named plan -- not made active: the comparison on the
    page now shows it, and switching to it is the user's own click."""
    body = _body()
    data = store()
    if data.empty:
        return payload({"error": "Aucun relevé importé."}), 404
    live = _plan()
    horizon = months_ahead(request.args)
    action = body.get("action") or "preview"

    if action == "save":
        name = str(body.get("name") or "").strip()
        changes = _clean(body.get("changes"))
        if not name or len(name) > 60 or ":" in name:
            return payload({"errors": {"name": "Un nom de 60 caractères au plus, sans « : »."}}), 400
        if name in live.plan_scenarios:
            return payload({"errors": {"name": "Ce nom est déjà pris."}}), 400
        copy = plans_module._detached(live._declarations(), live.installments)
        problems = _apply_changes(copy, changes)
        if problems or not changes:
            return payload({"errors": {"changes": problems[0] if problems else "Aucun changement."}}), 400
        live.plan_scenarios[name] = copy._declarations()
        live.save()
        return payload({"ok": True, "name": name})

    config, refused = _config()
    if refused:
        return refused
    sentence = str(body.get("sentence") or "").strip()[:400]
    if not sentence:
        return payload({"error": "La phrase est vide."}), 400
    today = data.statement.period_end
    context = {
        "phrase": sentence,
        "releve_au": today.isoformat(),
        "mois_prochain": plans_module.month_key(plans_module._add_months(today, 1)),
        "plan_actuel": {
            "revenu_mensuel": live.income, "depense_mensuelle": live.spend,
            "versements": live.contributions,
            "ponctuels": [{"libelle": e["label"], "mois": e.get("month"), "montant": e["amount"]}
                          for e in live.one_offs],
        },
    }
    system = (assist.LANG + "Tu traduis une phrase en modifications d'un plan de trésorerie. "
              "Actions : contrib = un versement récurrent vers une poche (pocket 3a ou "
              "taxable = le placement, IBKR compris ; every month/quarter/semester/year ; "
              "months = durée en mois, 480 si aucune fin n'est dite ; start = AAAA-MM du "
              "premier versement) ; add = une dépense ponctuelle (label, amount, date "
              "AAAA-MM-JJ ou month AAAA-MM, destination '' pour une dépense, 3a ou taxable "
              "pour un virement vers une poche) ; income = revenu mensuel ; spend = "
              "dépense mensuelle habituelle. amount : en CHF, positif. Ne choisis jamais un "
              "rendement : ce n'est pas une action. Si la phrase demande autre chose que "
              "ces actions, supported = false et note dit pourquoi. Si la phrase fixe un "
              "plancher de cash à ne pas franchir (« ne pas descendre sous 15k »), mets floor "
              "= ce montant en CHF (15k = 15000), supported = true et changes vide : l'app "
              "calcule elle-même ce qu'il faut ajuster. Sinon floor = null. name : un nom "
              "court pour le scénario.")
    try:
        answer = ai.ask_json(config, "scenario", system,
                             json.dumps(context, ensure_ascii=False, default=str),
                             SCENARIO_SCHEMA)
    except ai.AIError as e:
        return _failed(e)
    floor_note, options, lever = None, [], None
    if answer["supported"] and not answer["changes"] and isinstance(answer["floor"], (int, float)) \
            and answer["floor"] > 0:
        changes, floor_note, options, lever = _floor_changes(
            data, live, horizon, float(answer["floor"]), body.get("lever") or None)
        if not changes:
            return payload({"supported": False, "note": floor_note, "options": options})
        answer["name"] = answer["name"] or f"Plancher {analysis.chf(answer['floor'], 0)}"
    elif not answer["supported"] or not answer["changes"]:
        return payload({"supported": False,
                        "note": answer["note"] or "Cette phrase ne se traduit pas en plan."})
    else:
        changes = _clean(answer["changes"])
    copy = plans_module._detached(live._declarations(), live.installments)
    problems = _apply_changes(copy, changes)
    if problems:
        return payload({"supported": False, "note": problems[0], "changes": changes}), 422
    return payload({
        "supported": True,
        "name": answer["name"].strip()[:60].replace(":", " ") or "Scénario",
        "changes": [{**c, "text": _describe(c), "rows": _diff_rows(c, live)} for c in changes],
        "floor_note": floor_note,
        "floor": float(answer["floor"]) if floor_note else None,
        "options": options,
        "lever": lever,
        "base": _projection(data, live, horizon),
        "scenario": _projection(data, copy, horizon),
        "horizon": horizon,
    })
