"""The engine: run a use case over a sheet of items, property by property.

For each phase it
  1. runs the gate (required fields in code, the intake questions by the model); an item that fails
     reads "Not assessed" in every other property, with the reason in the observation;
  2. orders the remaining properties by what they build on (`uses`), so independent ones run together;
  3. for every (item, property) gathers evidence from the property's plan, asks the model, verifies;
  4. saves each cell the moment it is decided, and records an event so the screen can follow along;
  5. when a property needs a source and none was found, opens a question for the architect and carries
     on: nothing else waits. An answer re-runs only the properties that build on it;
  6. writes the summary properties last, from everything decided, and fills the citations property.

Everything the engine touches outside itself comes through `Tools`, so the same code runs in the
service and in tests.
"""

from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from eawiki.cases import gather as gmod
from eawiki.cases import plan as pmod
from eawiki.cases import profile as profmod
from eawiki.cases import solve as smod
from eawiki.cases.store import CaseStore

DEFAULT_GATE_COLUMN = "Is it a true demand?"


def phase_id(stage: dict) -> str:
    return stage.get("id") or re.sub(r"[^a-z0-9]+", "-", (stage.get("name") or "phase").lower()).strip("-")


def gate_column(spec: dict) -> str:
    return (spec.get("validation") or {}).get("result_column") or DEFAULT_GATE_COLUMN


def summary_columns(stage: dict) -> list[str]:
    return list(stage.get("summary_columns") or [])


def levels(columns: list[dict]) -> list[list[dict]]:
    """Group properties into rounds: a property comes after everything it builds on."""
    names = {c["name"] for c in columns}
    remaining = list(columns)
    done: set = set()
    out: list[list[dict]] = []
    while remaining:
        ready = [c for c in remaining if all((u in done) or (u not in names) for u in (c.get("uses") or []))]
        if not ready:                               # a cycle: do not hang, run the rest together
            ready = remaining
        out.append(ready)
        done |= {c["name"] for c in ready}
        remaining = [c for c in remaining if c not in ready]
    return out


def steps(spec: dict, stage: dict, first: bool) -> list[dict]:
    """The rounds a phase runs, in order, so the screen can show a segmented bar: the gate, then
    each level of properties, then the summaries. Mirrors run_phase."""
    gname = gate_column(spec)
    cols = stage["output"]["columns"]
    out = []
    by = {c["name"]: c for c in cols}

    def label(names: list[str]) -> str:
        c = by[names[0]]
        return c.get("activity") or f"Working out {names[0]}"

    if first and (spec.get("validation") or {}).get("enabled") is not False and any(c["name"] == gname for c in cols):
        out.append({"label": label([gname]), "columns": [gname]})
    summ = set(summary_columns(stage))
    skip = {gname} if first else set()
    main = [c for c in cols if c["name"] not in skip | summ and c.get("type") != "citations"]
    for level in levels(main):
        out.append({"label": label([c["name"] for c in level]), "columns": [c["name"] for c in level]})
    last = [c["name"] for c in cols if c["name"] in summ]
    if last:
        out.append({"label": label(last), "columns": last})
    return out


def _show(v) -> str:
    return "; ".join(map(str, v)) if isinstance(v, list) else str(v)


class Engine:
    def __init__(self, store: CaseStore, tools_factory: Callable[[], gmod.Tools], workers: Optional[int] = None):
        self.store = store
        self.tools_factory = tools_factory
        self.workers = workers or int(os.environ.get("EAWIKI_UC_WORKERS", "6"))
        self._cancel: set = set()
        self._plans: dict = {}
        self._profiles: dict = {}                # (case, item) -> what the demand mentions
        from eawiki.cases import flow
        self.phase_graph = flow.build_phase_graph(self)
        self.cell_graph = flow.build_cell_graph(self)

    # ---- starting ----------------------------------------------------------------------
    def create(self, spec: dict, items: list[dict], name: str) -> str:
        from eawiki.query import executor
        items = [dict(it) for it in items]
        for i, it in enumerate(items):
            it["_id"] = str(it.get("_id") or executor._item_id(it, i, spec))
        return self.store.create_case(spec.get("id", ""), name, spec, items)

    def start(self, cid: str, background: bool = True) -> None:
        case = self.store.get_case(cid)
        first = phase_id(case["spec"]["stages"][0])
        self._spawn(lambda: self.run_phase(cid, first), background)

    @staticmethod
    def _spawn(fn: Callable, background: bool) -> None:
        if background:
            threading.Thread(target=fn, daemon=True).start()
        else:
            fn()

    def cancel(self, cid: str) -> None:
        self._cancel.add(cid)

    # ---- one phase ---------------------------------------------------------------------
    def _rows(self, case: dict, idx: int) -> list[dict]:
        items = case["items"]
        if idx == 0:
            return items
        prev = phase_id(case["spec"]["stages"][idx - 1])
        gate = {c["item_id"]: c for c in self.store.cells(case["id"], prev) if c["column"] == gate_column(case["spec"])}
        return [it for it in items if gate.get(it["_id"], {}).get("value") == "Yes"]

    def run_phase(self, cid: str, pid: str, only_item: Optional[str] = None,
                  only_cols: Optional[set] = None, resume: bool = False) -> None:
        """Run one phase through the phase graph (see eawiki.cases.flow). A run that fails is recorded
        on the phase, so the screen can say so and offer to resume; `resume` keeps what was decided."""
        run = {"pool": ThreadPoolExecutor(max_workers=self.workers)}
        try:
            self._cancel.discard(cid)
            self.phase_graph.invoke({"cid": cid, "pid": pid, "only_item": only_item, "only_cols": only_cols,
                                     "run": run, "li": 0, "resume": resume})
        except Exception as e:
            if not only_item:
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                self.store.set_phase(cid, pid, status="error", error=msg, preparing=False)
                self.store.add_event(cid, "error", {"phase": pid, "error": msg})
            raise
        finally:
            run["pool"].shutdown(wait=True)

    def resume(self, cid: str, pid: str, background: bool = True) -> dict:
        """Run the phase again, keeping every cell already decided and every answer from the architect."""
        case = self.store.get_case(cid)
        if not case or not any(phase_id(x) == pid for x in case["spec"]["stages"]):
            raise ValueError("no such phase")
        self._spawn(lambda: self.run_phase(cid, pid, resume=True), background)
        return {"phase": pid, "status": "resuming"}

    # ---- the phase graph's nodes ------------------------------------------------------
    def _n_prepare(self, s) -> dict:
        cid, pid, only_item, only_cols, run = s["cid"], s["pid"], s["only_item"], s["only_cols"], s["run"]
        st = self.store
        case = st.get_case(cid)
        spec = case["spec"]
        stages = spec["stages"]
        idx = next(i for i, x in enumerate(stages) if phase_id(x) == pid)
        stage = stages[idx]
        cols = stage["output"]["columns"]
        rows = self._rows(case, idx)
        if only_item:
            rows = [r for r in rows if r["_id"] == only_item]
        if not only_item:                      # visible at once: planning each property can take a while
            st.set_phase(cid, pid, status="running", started=time.time(), total=len(rows), approved=False,
                         preparing=True, error="")
            st.add_event(cid, "phase_start", {"phase": pid, "items": len(rows), "properties": len(cols)})
        tools = self.tools_factory()
        fields = [f["name"] for f in (spec.get("input") or {}).get("item_fields") or []]
        docs = tools.doc_ids()
        with ThreadPoolExecutor(max_workers=self.workers) as px:
            plans = dict(zip([c["name"] for c in cols], px.map(
                lambda c: pmod.build_plan(c, fields, docs, tools.llm_json, self._plans), cols)))
        if not only_item:
            st.set_phase(cid, pid, preparing=False)
        done = {(c["item_id"], c["column"]) for c in st.cells(cid, pid)
                if (c["source"] == "user" or c["status"] == "user")
                or (s.get("resume") and c["status"] in ("answered", "not_assessed", "needs_source"))}
        skip = {gate_column(spec)} if idx == 0 else set()
        summary = set(summary_columns(stage))
        main = [c for c in cols if c["name"] not in skip | summary and c.get("type") != "citations"]
        if only_cols is not None:
            main = [c for c in main if c["name"] in only_cols]
        run.update(spec=spec, stage=stage, idx=idx, cols=cols, rows=rows, passing=rows, tools=tools, plans=plans,
                   link_cache={}, done=done, rounds=levels(main),
                   last=[c for c in cols if c["name"] in summary and (only_cols is None or c["name"] in only_cols)])
        return {"li": 0}

    def _n_gate(self, s) -> dict:
        run, cid, pid = s["run"], s["cid"], s["pid"]
        spec, idx, rows = run["spec"], run["idx"], run["rows"]
        if idx == 0 and (spec.get("validation") or {}).get("enabled") is not False and not s["only_item"]:
            have = {c["item_id"]: c for c in self.store.cells(cid, pid) if c["column"] == gate_column(spec)}
            if s.get("resume") and all(r["_id"] in have for r in rows):
                run["passing"] = [r for r in rows if have[r["_id"]]["value"] == "Yes"]
            else:
                run["passing"] = self._gate(cid, pid, spec, run["stage"], rows, run["tools"], run["pool"])
        if s["only_item"] and idx == 0:
            gc = {c["column"]: c for c in self.store.cells(cid, pid) if c["item_id"] == s["only_item"]}.get(gate_column(spec))
            run["passing"] = rows if (gc and gc["value"] == "Yes") or not gc else []
        return {}

    def _profile_of(self, cid: str, it: dict, run: dict) -> dict:
        key = (cid, it["_id"])
        if key not in self._profiles:
            self._profiles[key] = profmod.build_profile(gmod.labelled_fields(run["spec"], it), run["tools"].llm_json)
        return self._profiles[key]

    def _n_profile(self, s) -> dict:
        """Read what each passing demand mentions, once, so lookups can search its mentions one by one."""
        run, cid, pid = s["run"], s["cid"], s["pid"]
        if run["passing"] and not s["only_item"]:
            self.store.set_phase(cid, pid, preparing=True, prep="Reading what each demand mentions")
        run["profiles"] = dict(run["pool"].map(lambda it: (it["_id"], self._profile_of(cid, it, run)), run["passing"]))
        if not s["only_item"]:
            self.store.set_phase(cid, pid, preparing=False, prep="")
        return {}

    def _n_round(self, s) -> dict:
        run = s["run"]
        self._run_level(s["cid"], s["pid"], run["rounds"][s["li"]], run)
        return {"li": s["li"] + 1}

    def _n_summaries(self, s) -> dict:
        run = s["run"]
        if run["last"]:
            self._run_level(s["cid"], s["pid"], run["last"], run)
        return {}

    def _n_citations(self, s) -> dict:
        run = s["run"]
        for c in run["cols"]:                                              # citations: a union, in code
            if c.get("type") == "citations":
                self._citations(s["cid"], s["pid"], c, run["rows"])
        return {}

    def _n_consistency(self, s) -> dict:
        """Checks that need more than one item, done in code. Duplicates: if one demand names another as
        its duplicate, the other names it back. Where the other says it is not a duplicate at all, the
        two disagree and the architect is asked, because code cannot say which is right."""
        run, cid, pid = s["run"], s["cid"], s["pid"]
        cfg = (run["stage"].get("consistency") or {}).get("duplicates")
        if not cfg or s["only_item"]:
            return {}
        ids = {it["_id"] for it in run["rows"]}
        cells = {(c["item_id"], c["column"]): c for c in self.store.cells(cid, pid)}
        pat = re.compile("|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True))) if ids else None
        if pat is None:
            return {}
        for it in run["rows"]:
            a = it["_id"]
            flag = cells.get((a, cfg["flag"]))
            ref = cells.get((a, cfg["ref"]))
            if not flag or not ref or _show(flag["value"]) not in cfg["yes"]:
                continue
            for b in dict.fromkeys(x for x in pat.findall(_show(ref["value"])) if x != a):
                bflag, bref = cells.get((b, cfg["flag"])), cells.get((b, cfg["ref"]))
                if not bref or a in _show(bref["value"]):
                    continue
                if bflag and _show(bflag["value"]) in cfg["yes"]:
                    now = (_show(bref["value"]).strip() or "").strip()
                    now = "" if now.lower() in ("none", "") else now
                    self.store.save_cell(cid, b, pid, cfg["ref"], value=(now + "; " if now else "") + a, status="answered",
                                         source="rule", evidence=bref["evidence"],
                                         how=bref["how"] + [f"{a} names {b} as a duplicate, so {b} names {a} too (duplicates are mirrored in code)."])
                    self.store.add_event(cid, "cell", {"phase": pid, "item": b, "column": cfg["ref"], "status": "answered"})
                elif bflag:
                    self.store.add_question(cid, b, pid, cfg["flag"],
                                            f"{a} says it duplicates {b}, but {b} is marked '{_show(bflag['value'])}'. Which is right?",
                                            {"needs": "The two demands disagree about whether they are duplicates.", "looked": "the answers of both demands", "suggestions": []})
                    self.store.add_event(cid, "question", {"phase": pid, "item": b, "column": cfg["flag"]})
        return {}

    def _n_finish(self, s) -> dict:
        cid, pid = s["cid"], s["pid"]
        if not s["only_item"]:
            n_q = sum(1 for q in self.store.questions(cid) if q["status"] == "open" and q["phase_id"] == pid)
            self.store.set_phase(cid, pid, status="review", finished=time.time(), open_questions=n_q)
            self.store.add_event(cid, "phase_done", {"phase": pid, "open_questions": n_q})
        self._cancel.discard(cid)
        return {}

    # ---- the gate ----------------------------------------------------------------------
    def _gate(self, cid, pid, spec, stage, rows, tools, pool) -> list[dict]:
        from eawiki.query import executor
        gname = gate_column(spec)
        gcol = next((c for c in stage["output"]["columns"] if c["name"] == gname), None)
        if gcol is None:
            return rows
        self.store.add_event(cid, "step", {"phase": pid, "label": "Check each is a true demand", "column": gname})

        def one(it):
            g = smod.gate(spec, it, tools.llm_json, executor._missing_required(spec, it))
            self.store.save_cell(cid, it["_id"], pid, gname, value=g["outcome"], status="answered", source="rule",
                                 how=[g["reason"] or "Every intake question was answered yes."])
            self.store.add_event(cid, "cell", {"phase": pid, "item": it["_id"], "column": gname})
            return it, g

        results = list(pool.map(one, rows))
        passing = [it for it, g in results if g["outcome"] == "Yes"]
        for it, g in results:
            if g["outcome"] != "Yes":
                self._not_assessed(cid, pid, stage, spec, it, g)
        return passing

    def _not_assessed(self, cid, pid, stage, spec, it, g) -> None:
        gname = gate_column(spec)
        summ = set(summary_columns(stage))
        for c in stage["output"]["columns"]:
            if c["name"] == gname:
                continue
            if c["name"] in summ:
                self.store.save_cell(cid, it["_id"], pid, c["name"],
                                     value=f"{g['outcome']}. {g['reason']}".strip(), status="answered", source="rule",
                                     how=["Written from the gate result: this demand was not assessed further."])
            elif c.get("type") == "citations":
                self.store.save_cell(cid, it["_id"], pid, c["name"], value=[], status="not_assessed", source="rule")
            else:
                self.store.save_cell(cid, it["_id"], pid, c["name"], value=smod.not_assessed_value(c),
                                     status="not_assessed", source="rule",
                                     how=["Skipped: the demand did not pass the gate."])

    # ---- one round of properties -----------------------------------------------------
    def _decided(self, cid: str, pid: str, item_id: str) -> dict:
        out = {}
        for c in self.store.cells(cid, pid):
            if c["item_id"] != item_id:
                continue
            out[c["column"]] = "(unknown: asked the architect)" if c["status"] == "needs_input" else _show(c["value"])
        return out

    def _decided_values(self, cid: str, pid: str, item_id: str) -> dict:
        """What the earlier properties of this item decided (their real values, for a lookup to start from)."""
        return {c["column"]: c["value"] for c in self.store.cells(cid, pid) if c["item_id"] == item_id and c["status"] in ("answered", "user")}

    def _run_level(self, cid, pid, level, run) -> None:
        names = ", ".join(c["name"] for c in level)
        self.store.add_event(cid, "step", {"phase": pid, "label": names, "columns": [c["name"] for c in level]})
        tasks = [(it, c) for c in level for it in run["passing"]]

        def one(t):
            it, col = t
            if cid in self._cancel or (it["_id"], col["name"]) in run["done"]:
                return                                   # stopped, or already decided (the architect's own answer, or a resume)
            self.cell_graph.invoke({"cid": cid, "pid": pid, "spec": run["spec"], "item": it, "col": col,
                                    "others": [o for o in run["rows"] if o["_id"] != it["_id"]],
                                    "plan": run["plans"][col["name"]], "tools": run["tools"],
                                    "link_cache": run["link_cache"], "hint": None, "question": None,
                                    "profile": run["profiles"].get(it["_id"])})

        list(run["pool"].map(one, tasks))

    # ---- the cell graph's nodes -------------------------------------------------------
    def _c_gather(self, s) -> dict:
        try:
            ev = gmod.gather(s["tools"], s["plan"], s["spec"], s["item"], s["others"], s["link_cache"], s.get("hint"),
                             s.get("profile"), self._decided_values(s["cid"], s["pid"], s["item"]["_id"]))
            return {"ev": ev, "failed": False}
        except Exception as e:                                   # one property failing never stops the sheet
            return {"failed": True, "cell": self._failed_cell(s["col"], e), "ev": {"looked": ""}}

    def _c_solve(self, s) -> dict:
        if s.get("failed"):
            return {}
        try:
            cell = smod.solve(s["col"], s["item"], s["spec"], s["ev"], self._decided(s["cid"], s["pid"], s["item"]["_id"]),
                              s["tools"].llm_json)
        except Exception as e:
            cell = self._failed_cell(s["col"], e)
        return {"cell": cell}

    @staticmethod
    def _failed_cell(col: dict, e: Exception) -> dict:
        return {"value": [] if col.get("type") == "list" else "", "status": "needs_input", "evidence": [], "source": "model",
                "how": [f"The step failed ({type(e).__name__})."],
                "need": col.get("info_needed") or f"'{col['name']}' could not be decided."}

    def _save(self, s, cell: dict, how=None, status=None) -> None:
        self.store.save_cell(s["cid"], s["item"]["_id"], s["pid"], s["col"]["name"], value=cell["value"],
                             status=status or cell["status"], source=cell["source"], evidence=cell["evidence"],
                             how=how or cell["how"], need=cell["need"] if (status or cell["status"]) != "answered" else "")
        self.store.add_event(s["cid"], "cell", {"phase": s["pid"], "item": s["item"]["_id"], "column": s["col"]["name"],
                                                "status": status or cell["status"]})

    def _c_save_answer(self, s) -> dict:
        self._save(s, s["cell"])
        return {}

    def _c_open_question(self, s) -> dict:
        """The human step: save what is known, ask, and end. Nothing waits."""
        cell, cid, pid, it, col = s["cell"], s["cid"], s["pid"], s["item"], s["col"]
        self._save(s, cell)
        self.store.add_question(cid, it["_id"], pid, col["name"], cell.get("question") or cell["need"],
                                {"needs": cell["need"], "looked": cell.get("looked", ""),
                                 "suggestions": cell.get("suggestions", [])})
        self.store.add_event(cid, "question", {"phase": pid, "item": it["_id"], "column": col["name"]})
        return {}

    def _c_look_found(self, s) -> dict:
        cell, q, h = s["cell"], s["question"], s["hint"]
        pointed = "; ".join(x for x in (f"document {h['document']}" if h.get("document") else "", h.get("where") or "") if x)
        self._save(s, cell, how=[f"The architect pointed to: {pointed}."] + cell["how"], status="answered")
        self.store.close_question(q["id"], "answered", f"look: {pointed}")
        self.store.add_event(s["cid"], "question_closed", {"id": q["id"]})
        return {}

    def _c_look_missed(self, s) -> dict:
        cell, q, h = s["cell"], s["question"], s["hint"]
        pointed = "; ".join(x for x in (f"document {h['document']}" if h.get("document") else "", h.get("where") or "") if x)
        looked = (s.get("ev") or {}).get("looked") or "nothing came back"
        self.store.set_question_meta(q["id"], looked=f"{pointed}: {looked}. Nothing there decides '{s['col']['name']}'. "
                                                      "Point somewhere else, or give the value.")
        self.store.add_event(s["cid"], "question", {"phase": s["pid"], "item": s["item"]["_id"], "column": s["col"]["name"], "retry": True})
        return {}

    def _citations(self, cid, pid, col, rows) -> None:
        by_item: dict = {}
        for c in self.store.cells(cid, pid):
            if c["column"] != col["name"]:
                by_item.setdefault(c["item_id"], []).extend(e for e in c["evidence"] if not e.startswith("demand:"))
        for it in rows:
            ids = list(dict.fromkeys(by_item.get(it["_id"], [])))
            self.store.save_cell(cid, it["_id"], pid, col["name"], value=ids, status="answered" if ids else "none",
                                 source="rule", how=["Every source block cited by the answers above."])

    # ---- the architect answers a question ------------------------------------------
    def answer(self, qid: str, answer: Optional[str], background: bool = True, via: Optional[str] = None) -> dict:
        q = self.store.get_question(qid)
        if not q or q["status"] != "open":
            raise ValueError("no such open question")
        case = self.store.get_case(q["case_id"])
        stage = next(s for s in case["spec"]["stages"] if phase_id(s) == q["phase_id"])
        col = next(c for c in stage["output"]["columns"] if c["name"] == q["column"])
        if answer is None or not answer.strip():
            self.store.close_question(qid, "skipped")
            self.store.add_event(q["case_id"], "question_closed", {"id": qid, "skipped": True})
            return {"id": qid, "status": "skipped"}
        text = answer.strip()
        value = [v.strip() for v in re.split(r"[;\n]", text) if v.strip()] if col.get("type") == "list" else text
        how = ("The architect picked a suggestion from the sources, so this is recorded as theirs, not as a sourced fact. Question: "
               if via == "suggestion" else "Supplied by the architect in answer to: ") + q["text"]
        self.store.save_cell(q["case_id"], q["item_id"], q["phase_id"], q["column"], value=value, status="user",
                             source="user", how=[how])
        self.store.close_question(qid, "answered", ("suggestion: " if via == "suggestion" else "") + text)
        self.store.add_event(q["case_id"], "cell", {"phase": q["phase_id"], "item": q["item_id"], "column": q["column"], "status": "user"})
        dependants = self._dependants(stage, q["column"])
        if dependants:
            self._spawn(lambda: self.run_phase(q["case_id"], q["phase_id"], only_item=q["item_id"], only_cols=dependants), background)
        return {"id": qid, "status": "answered", "rerun": sorted(dependants)}

    def look(self, qid: str, document: Optional[str], where: Optional[str], background: bool = True) -> dict:
        """The architect says where to look instead of giving the value: search that document (and
        that wording) for this one cell. A cited answer is stored like any other; if nothing usable
        is found the question stays open and says what was tried. Nothing is guessed."""
        q = self.store.get_question(qid)
        if not q or q["status"] != "open":
            raise ValueError("no such open question")
        document, where = (document or "").strip() or None, (where or "").strip()
        if not document and not where:
            raise ValueError("Name a document, or say where to look.")
        tools = self.tools_factory()
        if document and document not in (tools.doc_ids() or []):
            raise ValueError(f"'{document}' is not an ingested document. Add it under Sources, or give the value.")
        self._spawn(lambda: self._look(q, document, where, tools), background)
        return {"id": qid, "status": "looking"}

    def _look(self, q: dict, document: Optional[str], where: str, tools) -> None:
        cid, pid = q["case_id"], q["phase_id"]
        case = self.store.get_case(cid)
        spec = case["spec"]
        stage = next(x for x in spec["stages"] if phase_id(x) == pid)
        col = next(c for c in stage["output"]["columns"] if c["name"] == q["column"])
        it = next(i for i in case["items"] if i["_id"] == q["item_id"])
        fields = [f["name"] for f in (spec.get("input") or {}).get("item_fields") or []]
        plan = pmod.build_plan(col, fields, tools.doc_ids(), tools.llm_json, self._plans)
        prof = self._profiles.get((cid, it["_id"])) or profmod.build_profile(gmod.labelled_fields(spec, it), tools.llm_json)
        self._profiles[(cid, it["_id"])] = prof
        out = self.cell_graph.invoke({"cid": cid, "pid": pid, "spec": spec, "item": it, "col": col, "plan": plan, "profile": prof,
                                      "others": [o for o in case["items"] if o["_id"] != it["_id"]], "tools": tools,
                                      "link_cache": {}, "hint": {"document": document, "where": where}, "question": q})
        if out["cell"]["status"] == "answered":
            deps = self._dependants(stage, col["name"])
            if deps:
                self.run_phase(cid, pid, only_item=it["_id"], only_cols=deps)

    @staticmethod
    def _dependants(stage: dict, column: str) -> set:
        """Every property that builds on `column`, directly or through others, plus the summaries."""
        cols = stage["output"]["columns"]
        out, grew = set(), True
        base = {column}
        while grew:
            grew = False
            for c in cols:
                if c["name"] not in out and set(c.get("uses") or []) & (base | out):
                    out.add(c["name"])
                    grew = True
        return out | set(summary_columns(stage))

    # ---- review and the next phase --------------------------------------------------
    def approve(self, cid: str, pid: str, background: bool = True) -> dict:
        case = self.store.get_case(cid)
        stages = case["spec"]["stages"]
        idx = next(i for i, s in enumerate(stages) if phase_id(s) == pid)
        self.store.set_review(cid, pid, None, None, "approved")
        self.store.set_phase(cid, pid, status="approved", approved=True)
        self.store.add_event(cid, "phase_approved", {"phase": pid})
        nxt = phase_id(stages[idx + 1]) if idx + 1 < len(stages) else None
        if nxt:
            self._spawn(lambda: self.run_phase(cid, nxt), background)
        return {"approved": pid, "next": nxt}
