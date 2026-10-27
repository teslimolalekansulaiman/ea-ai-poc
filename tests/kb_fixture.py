"""A small, realistic knowledge base and 14 demands, for testing the by-name lookups.

It is SYNTHETIC. It stands in for what ingestion produces from the EA team's documents: catalogs of
applications, data, technology and security controls, a classification standard, a glossary, a
contract register and an initiative portfolio; a wiki page for every entity; and the graph. It is
built with the traps real documents have:

  * a name that is the data category "HR" and also part of "HR Legacy System" and an alias of the HR
    application, so "HR system" and "HR data" must not collapse into one entity;
  * "payroll", which is a service inside the HR & Payroll Portal and has no entry of its own;
  * "Oracle DB" / "Oracle Database 11", one platform under several names;
  * names that match nothing (field inspection tablets, website forms);
  * a vague demand that names nothing;
  * a misspelt and abbreviated mention.

The reference answers are judgments made by following the EA team's steps on this fixture. They are
not ground truth about a real organization; they exist so the lookups can be measured and kept honest.
The search stub is lexical: it tests the plumbing and the ranking logic, not the quality of embeddings.

Gold per demand: `mentions` (what the demand names, and the entity ids a careful reader would match each to; an empty list = the knowledge base has no entry), plus the answers for the six by-name properties.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The fixture depends on no retrieval code: it is test material only. The few helpers it needs are here.
GENERIC = {"system", "systems", "app", "apps", "application", "applications", "tool", "tools", "portal", "solution", "software", "service",
           "module", "platform", "server", "servers", "database", "data", "records", "record", "information", "report", "reports", "control", "controls"}
_KIND = {"physical_application_component": "app", "logical_application_component": "app", "logical_technology_component": "tech",
         "data_entity": "data", "control": "security"}


def _family(node_type):
    return _KIND.get(node_type)


def _tokens(s):
    out = []
    for t in re.findall(r"[^\W_]+(?:[-.][^\W_]+)*", str(s or "").casefold()):
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out

APP, DATA, TECH, CTRL = "physical_application_component", "data_entity", "logical_technology_component", "control"

# id, name, type, aliases, catalog doc, owner role, description, lifecycle/classification, controls (apps)
E = [
 ("C-201", "Finvera Finance System", APP, ["Finance system", "finance ERP", "Finvera"], "Finance Systems Lead", "General ledger, budgeting and the finance reporting exports.", "in use", ["SC-01", "SC-03"]),
 ("C-202", "Callwave Contact Centre Platform", APP, ["Contact centre platform", "contact center", "Callwave"], "Customer Experience Lead", "Telephony and case handling for customer services. Complaints are logged by agents.", "in use", ["SC-01", "SC-03"]),
 ("C-203", "Docuvia Document Management System", APP, ["Document management system", "DMS", "Docuvia"], "Administration Systems Lead", "Stores and routes contracts and administrative documents.", "in use", ["SC-01", "SC-03"]),
 ("C-204", "Peoplex HR System", APP, ["HR system", "HR app", "Peoplex", "Peoplex HR"], "HR Systems Lead", "Core HR records, leave and the monthly payroll export. Hosted on the Oracle database platform.", "in use", ["SC-01", "SC-03"]),
 ("C-205", "Datavia Data Warehouse and BI Platform", APP, ["Data warehouse", "EDW", "BI platform", "Datavia"], "Head of Data Office", "Central data warehouse and reporting platform fed by the finance, HR and procurement systems.", "in use", ["SC-01", "SC-03"]),
 ("C-206", "Attendance System", APP, ["Attendance application"], "HR Systems Lead", "Reads clock-in data from the fingerprint machines through the attendance gateway and passes it to the HR system.", "in use", ["SC-01"]),
 ("C-207", "HR & Payroll Portal", APP, [], "Central HR Entity Lead", "External portal run by the Central HR Entity: HR operations, employee self-service and the payroll system. Built on SAP with an Oracle database.", "in use", ["SC-01", "SC-02", "SC-03"]),
 ("C-208", "HR Legacy System", APP, ["legacy HR"], "HR Systems Lead", "Formerly managed payroll and HR. Migrated to the HR & Payroll Portal in 2020. Employees can still view their old records.", "retired", ["SC-01"]),
 ("C-209", "Training and Development Pages", APP, ["training pages", "training portal"], "HR Training Lead", "Intranet pages where employees view training programs and submit requests.", "in use", ["SC-01"]),
 ("C-210", "Attendance Devices Gateway", APP, ["attendance devices", "fingerprint machines", "clock-in devices"], "Facilities IT Lead", "Collects clock-in events from the site attendance devices and forwards them to the attendance system.", "in use", ["SC-01"]),
 ("C-211", "Internal SMS Application", APP, ["SMS application", "SMS gateway", "SMS"], "Communications Systems Lead", "Sends notifications to employees by SMS. Used by HR and Public Relations.", "in use", ["SC-01"]),
 ("C-212", "Enterprise Email Service", APP, ["email", "e-mail", "mail service"], "Infrastructure Services Lead", "Corporate email for all staff and shared mailboxes.", "in use", ["SC-01", "SC-03"]),
 ("C-213", "Customer Relationship Management System", APP, ["CRM", "customer relationship system"], "Customer Experience Lead", "Customer records, interactions and campaigns.", "in use", ["SC-01", "SC-03"]),
 ("C-214", "Procurement Portal", APP, ["procurement system", "e-procurement"], "Procurement Systems Lead", "Purchase requests, tenders and vendor management.", "in use", ["SC-01"]),
 ("C-215", "Identity and Access Service", APP, ["identity service", "SSO", "single sign-on"], "Lead Security Architect", "Central sign-in, single sign-on and multi-factor authentication for staff applications.", "in use", ["SC-01", "SC-02"]),
 ("C-216", "Intranet Portal", APP, ["intranet"], "Communications Systems Lead", "The staff intranet: news, directories and links to services.", "in use", ["SC-01"]),
 ("DE-01", "HR", DATA, ["human resources data", "HR data"], "HR Data Steward", "The data category covering the organization's human capital: recruitment, employee information, job rules and trainings.", "Confidential", []),
 ("DE-02", "Employee Master Data", DATA, ["employee data", "employee records", "staff records"], "HR Data Steward", "Name, grade, contact details and leave balance of each employee.", "Confidential", []),
 ("DE-03", "Leave and Attendance Records", DATA, ["leave data", "attendance records", "leave requests"], "HR Data Steward", "Leave requests, approvals and clock-in records.", "Confidential", []),
 ("DE-04", "Financial Reports", DATA, ["finance reports", "regulatory reports", "financial statements"], "Finance Data Steward", "Statutory and management financial reports.", "Confidential", []),
 ("DE-05", "Complaint Records", DATA, ["complaints", "customer complaints"], "Customer Data Steward", "Each complaint with the complainant's contact details, channel, status and handler.", "Confidential", []),
 ("DE-06", "Contract Documents", DATA, ["contracts", "agreements"], "Legal Data Steward", "Signed contracts and their amendments.", "Confidential", []),
 ("DE-07", "Customer Master Data", DATA, ["customer data", "customer records"], "Customer Data Steward", "Names, contact details and identifiers of customers.", "Confidential", []),
 ("DE-08", "Procurement Data", DATA, ["purchase orders", "vendor data", "spend data"], "Procurement Data Steward", "Purchase orders, tenders and vendor invoices.", "Internal", []),
 ("DE-09", "Published Policies", DATA, ["policies"], "Governance Data Steward", "Policies approved for publication on the website.", "Public", []),
 ("DE-10", "Security Audit Logs", DATA, ["audit logs"], "Security Data Steward", "Sign-in and access logs of the staff applications.", "Restricted", []),
 ("DE-11", "Training Records", DATA, ["training data", "training history"], "HR Data Steward", "Courses attended by each employee and their results.", "Internal", []),
 ("DE-12", "Payroll Data", DATA, ["salary data", "payroll data"], "Finance Data Steward", "Salary, allowances and deductions by employee.", "Restricted", []),
 ("T-01", "Oracle Database Platform", TECH, ["Oracle DB", "Oracle Database", "Oracle Database 11"], "Infrastructure Services Lead", "On-premises Oracle database platform. Hosts the HR system, the HR & Payroll Portal and the finance system.", "in use", []),
 ("T-02", "On-premises File Servers", TECH, ["file servers", "shared drives"], "Infrastructure Services Lead", "Windows file servers holding departmental shared folders.", "in use", []),
 ("T-03", "Cloud Storage Service", TECH, ["cloud storage"], "Infrastructure Services Lead", "Government-approved cloud object storage, available for departmental archives.", "in use", []),
 ("SC-01", "Identity and Access Management", CTRL, ["IAM", "sign-in", "access control"], "Lead Security Architect", "Controls who can sign in and what they can reach: accounts, roles and access reviews.", "", []),
 ("SC-02", "Multi-factor Authentication", CTRL, ["MFA", "two-factor"], "Lead Security Architect", "A second proof of identity at sign-in.", "", []),
 ("SC-03", "Data Protection", CTRL, ["encryption", "DLP", "data loss prevention"], "Lead Security Architect", "Encryption at rest and in transit, and data loss prevention for Confidential and Restricted data.", "", []),
 ("SC-04", "Security Monitoring", CTRL, ["SIEM", "monitoring"], "Lead Security Architect", "Collection and review of security events.", "", []),
]
RANK = {"Public": 0, "Internal": 1, "Confidential": 2, "Restricted": 3}
EDGES = [("C-204", "is_deployed_on", "T-01"), ("C-207", "is_deployed_on", "T-01"), ("C-201", "is_deployed_on", "T-01"),
         ("C-206", "communicates_with", "C-210"), ("C-206", "sends_data_to", "C-204"), ("C-204", "sends_data_to", "C-207"),
         ("C-208", "sends_data_to", "C-207"), ("C-205", "accesses", "C-201"), ("C-205", "accesses", "C-204"), ("C-205", "accesses", "C-214"),
         ("C-203", "communicates_with", "C-215"), ("C-209", "accesses", "DE-11"), ("C-204", "accesses", "DE-02"), ("C-204", "accesses", "DE-03")]

CATALOG_DOC = {APP: "Application_Catalog", DATA: "Data_Catalog", TECH: "Technology_Catalog", CTRL: "Security_Control_Catalog"}
DOCS = ["Application_Catalog", "Application_to_Security_Control_Matrix", "Contract_Register", "Data_Catalog", "Data_Classification_Standard",
        "Glossary_and_Aliases", "Initiative_Portfolio", "Security_Control_Catalog", "Technology_Catalog"]

EXTRA_BLOCKS = [
 ("Data_Classification_Standard", "Public: information approved for release outside the organization, such as published policies."),
 ("Data_Classification_Standard", "Internal: information for staff use whose release would cause minor harm, such as procurement data and training records."),
 ("Data_Classification_Standard", "Confidential: personal, financial or contractual information whose release would cause serious harm. Needs encryption and access control."),
 ("Data_Classification_Standard", "Restricted: information whose release would cause severe harm, such as payroll data and security logs. Where several data sets are involved, the highest classification applies."),
 ("Glossary_and_Aliases", "'the HR app' and 'the HR system' mean the Peoplex HR System (C-204). 'Payroll' is a service of the HR & Payroll Portal (C-207), not a separate application."),
 ("Glossary_and_Aliases", "'Oracle DB' and 'Oracle Database 11' mean the Oracle Database Platform (T-01)."),
 ("Contract_Register", "C-203 Docuvia: workflow engine and e-signature module licensed, not activated."),
 ("Contract_Register", "C-204 Peoplex: mobile add-on not purchased. Support contract to 2028."),
 ("Contract_Register", "C-202 Callwave: includes a case management module, not activated."),
 ("Initiative_Portfolio", "P-101 Finance system upgrade: reporting change freeze to 2027-01-15. Systems affected: Finvera Finance System, Datavia Data Warehouse."),
 ("Initiative_Portfolio", "P-103 HR system cloud migration: employee web portal in scope, mobile out of scope. Systems affected: Peoplex HR System."),
 ("Initiative_Portfolio", "P-104 Data warehouse phase 2: the HR subject area is planned for phase 3, not funded. Systems affected: Datavia Data Warehouse."),
 ("Initiative_Portfolio", "P-105 Document management rollout: the workflow and e-signature modules were left out for lack of budget. Systems affected: Docuvia Document Management System."),
 ("Initiative_Portfolio", "P-106 Website and mobile app redesign: includes the public web forms. Systems affected: website."),
]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


CATALOGUE_ONLY = {"DE-09", "DE-10", "SC-04"}      # listed only on a catalogue page: no page of their own
PAGE_REDIRECTS = {}


def build():
    nodes, blocks, pages = [], [], {}
    by_id = {}
    for eid, name, typ, aliases, owner, desc, extra, controls in E:
        n = {"node_id": eid, "name": name, "type": typ, "aliases": aliases, "ids": [eid] if re.match(r"[A-Z]+-\d+$", eid) else [], "slug": _slug(name),
             "owner": owner, "desc": desc, "extra": extra, "controls": controls}
        nodes.append(n)
        by_id[eid] = n
    counters: dict = {}

    def add_block(doc, text):
        counters[doc] = counters.get(doc, 0) + 1
        bid = f"{doc}:{counters[doc]}"
        blocks.append({"block_id": bid, "doc_id": doc, "text": text})
        return bid

    first_block = {}
    for n in nodes:
        doc = CATALOG_DOC[n["type"]]
        if n["type"] == APP:
            t = f"{n['node_id']} {n['name']}. {n['desc']} Owner role: {n['owner']}. Lifecycle: {n['extra']}."
        elif n["type"] == DATA:
            t = f"{n['name']}. {n['desc']} Classification: {n['extra']}. Owner role: {n['owner']}."
        else:
            t = f"{n['name']}. {n['desc']} Owner role: {n['owner']}."
        first_block[n["node_id"]] = add_block(doc, t)
    for n in nodes:
        if n["type"] == APP:
            ctrls = ", ".join(by_id[c]["name"] for c in n["controls"]) or "none recorded"
            add_block("Application_to_Security_Control_Matrix", f"{n['node_id']} {n['name']}: {ctrls}.")
    for doc, t in EXTRA_BLOCKS:
        add_block(doc, t)
    # The wiki has three page shapes (see eawiki/pages.py): a model-written page (free prose, inline citations, headings of
    # its own), a page built in code for a table-only item (italic type line, Attributes, Relationships), and an item
    # listed only on a catalogue page (no page of its own: a redirect points at its section). No heading is fixed.
    redirected = set(CATALOGUE_ONLY)
    catalogue = {}
    for n in nodes:
        edges = []
        for a2, r, b2 in EDGES:
            if a2 == n["node_id"]:
                edges.append(f"{n['name']} {r.replace('_', ' ')} {by_id[b2]['name']}")
            if b2 == n["node_id"]:
                edges.append(f"{by_id[a2]['name']} {r.replace('_', ' ')} {n['name']}")
        fam = _family(n["type"])
        label = {"app": "application", "data": "data entity", "tech": "technology component", "security": "security control"}[fam]
        blk = first_block[n["node_id"]]
        attrs = [f"Owner role: {n['owner']}"] + ([f"Classification: {n['extra']}"] if fam == "data" and n["extra"] else []) \
                + ([f"Lifecycle: {n['extra']}"] if fam == "app" else [])
        if n["node_id"] in redirected:
            catalogue.setdefault(CATALOG_DOC[n["type"]], []).append((n, label, blk, attrs, edges))
        elif fam == "app":
            lines = [f"# {n['name']}", "", f"{n['desc']} [{blk}]", "",
                     f"It is catalogued as {n['node_id']} and its owner role is {n['owner']} [{blk}]."]
            if edges:
                lines += ["", "## How it connects", ""] + [f"- {e} [{blk}]" for e in edges]
            pages[n["slug"]] = "\n".join(lines)
        else:
            lines = [f"# {n['name']}", "", f"*{label}* — listed in {CATALOG_DOC[n['type']]} [{blk}].", "", "## Attributes", ""] \
                    + [f"- {a2}" for a2 in attrs] + ["- " + n["desc"]]
            if edges:
                lines += ["", "## Relationships", ""] + [f"- {e}" for e in edges]
            pages[n["slug"]] = "\n".join(lines)
    redirects = {}
    for doc, items in catalogue.items():
        slug = f"catalogue-{_slug(doc)}-1"
        lines = [f"# {doc.replace('_', ' ')} — catalogue", "", f"{len(items)} items listed in {doc}.", ""]
        for n, label, blk, attrs, edges in items:
            lines += [f"## {n['name']}", "", f"*{label}* [{blk}]", ""] + [f"- {a2}" for a2 in attrs] + ["- " + n["desc"]] + [f"- {e}" for e in edges] + [""]
            redirects[n["slug"]] = {"page": slug, "name": n["name"]}
        pages[slug] = "\n".join(lines)
    PAGE_REDIRECTS.update(redirects)
    return nodes, blocks, pages, first_block


NODES, BLOCKS, PAGES, FIRST_BLOCK = build()
NODE_BY_ID = {n["node_id"]: n for n in NODES}


# ---- a lexical search stand-in (the real one is a vector search) ------------------------------------------
def _toks(s):
    return _tokens(s)


_DF: dict = {}
for _b in BLOCKS:
    for _t in set(_toks(_b["text"])):
        _DF[_t] = _DF.get(_t, 0) + 1


def search(q, k, docs):
    qt = set(_toks(q)) - GENERIC
    out = []
    for b in BLOCKS:
        if docs and b["doc_id"] not in docs:
            continue
        bt = set(_toks(b["text"]))
        hit = qt & bt
        if not hit:
            continue
        score = sum(math.log(1 + len(BLOCKS) / _DF.get(t, 1)) for t in hit)
        out.append((score, b))
    out.sort(key=lambda x: -x[0])
    return [dict(b) for _s, b in out[:k]]


def page(slug):
    """A wiki page by slug; an item listed only on a catalogue page comes back as its own section (as the product does)."""
    if slug in PAGES:
        return PAGES[slug]
    red = PAGE_REDIRECTS.get(slug)
    cat = PAGES.get(red["page"]) if red else None
    if not cat:
        return None
    sec = next((x for x in cat.split("\n## ")[1:] if x.splitlines()[0].strip() == red["name"]), None)
    return f"# {red['name']}\n\n" + "\n".join(sec.splitlines()[1:]).strip() if sec else None


def graph_facts(ids):
    facts = []
    for a, r, b in EDGES:
        if a in ids or b in ids:
            facts.append(f"{NODE_BY_ID[a]['name']} --{r}--> {NODE_BY_ID[b]['name']}")
    return {"facts": "\n".join(facts), "block_ids": [FIRST_BLOCK[i] for i in ids if i in FIRST_BLOCK]}


def doc_blocks(doc, limit):
    return [dict(b) for b in BLOCKS if b["doc_id"] == doc][:limit]


# ---- the 14 demands and their reference answers --------------------------------------------------------
# Domain follows the property's own step 4: Security is added when the data is Confidential or Restricted.
# Where the demand names an application only as the channel work arrives by today (email), it is not required
# of the answer and not held against it (see tests/e2e_names.py: an application the demand's own words name is a defensible extra).
def D(i, title, dept, need, outcome, rtype, urgency, reason, golive, systems, **gold):
    return {"item": {"demand_id": f"D-{i}", "date_submitted": "2026-09-01", "department": dept, "requester_role": "Head of " + dept,
                     "sponsor": "Director of " + dept, "title": title, "business_need": need, "expected_outcome": outcome,
                     "request_type": rtype, "requester_urgency": urgency, "urgency_reason": reason, "target_go_live": golive,
                     "systems_mentioned": systems}, "gold": gold}


DEMANDS = [
 D(101, "Employee self-service mobile app for leave and attendance", "Human Resources",
   "Employees request leave and check attendance by email and a paper form. Managers approve by email and HR re-types everything into the HR system. Approvals take 3 to 5 days and errors are common.",
   "Leave and attendance requests handled in under 1 day with no re-typing", "New solution", "High", "Peak leave season starts June 2027; internal audit finding on manual records", "2027-03-31",
   "HR system, payroll, attendance devices",
   mentions={"HR system": ["C-204"], "payroll": ["C-207"], "attendance devices": ["C-210"]},
   domain=["Application", "Security"], apps={"C-204", "C-207", "C-210"}, classification="Confidential", security={"SC-01", "SC-02", "SC-03"},
   artefact={"P-103", "C-204"}, owners={"HR Systems Lead", "Facilities IT Lead", "Central HR Entity Lead"},
   ask_ok=True, classification_ok={"Confidential", "Restricted"}),   # the demand lists payroll without saying whether payroll data is used: Confidential or Restricted, so a question is right
 D(102, "Automated regulatory financial reporting", "Finance",
   "A new mandatory digital financial reporting format starts next year. We export from the finance system into spreadsheets and rebuild the report by hand every quarter. It takes 6 working days and 3 people.",
   "Report produced in the mandated format in 1 day with a full audit trail", "Enhancement of existing", "Critical", "Mandated format takes effect on 1 Jan 2027", "2026-12-15",
   "Finance system, data warehouse",
   mentions={"Finance system": ["C-201"], "data warehouse": ["C-205"]},
   domain=["Application", "Security"], apps={"C-201", "C-205"}, classification="Confidential", security={"SC-01", "SC-03"},
   artefact={"C-201"}, owners={"Finance Systems Lead", "Head of Data Office"}),   # P-101 only freezes reporting changes: it constrains the date, it does not cover the need
 D(103, "Complaint tracking system", "Customer Services",
   "Complaints arrive by phone, email and the website and are tracked in different spreadsheets. We cannot see the status of a complaint or who is handling it, and we miss the 10-day response target for about 1 in 5 complaints.",
   "One view of every complaint with owner, status and response-time alerts", "New solution", "High", "Response-target breaches are reported to the Executive Committee every month", "2027-02-28",
   "Contact centre platform, website forms, email",
   mentions={"Contact centre platform": ["C-202"], "website forms": [], "email": ["C-212"]},
   domain=["Application", "Security"], apps={"C-202"}, classification="Confidential", security={"SC-01", "SC-03"},
   artefact={"C-202"}, owners={"Customer Experience Lead", "Infrastructure Services Lead"}),
 D(104, "Digital signature and e-approval for contracts", "Legal Affairs",
   "Contracts are printed, signed by hand and scanned. A signature cycle takes two weeks and documents are lost. We want contracts approved and signed digitally with the identity service.",
   "Contracts signed digitally within 2 days with an audit trail", "New solution", "High", "Government mandate on digital transformation of transactions", "2027-01-31",
   "Document management system, identity service",
   mentions={"Document management system": ["C-203"], "identity service": ["C-215"]},
   domain=["Application", "Security"], apps={"C-203", "C-215"}, classification="Confidential", security={"SC-01", "SC-02", "SC-03"},
   artefact={"C-203", "P-105"}, owners={"Administration Systems Lead", "Lead Security Architect"}),
 D(105, "Training pages: online booking and certificates", "Human Resources",
   "Employees cannot book training sessions online. They email the training team, who update the training records by hand. Certificates are issued manually.",
   "Employees book sessions and download certificates online", "Enhancement of existing", "Medium", "Training plan for next year opens in October", "2027-01-15",
   "training pages, HR system",
   mentions={"training pages": ["C-209"], "HR system": ["C-204"]},
   domain=["Application"], apps={"C-209", "C-204"}, classification="Internal", security={"SC-01", "SC-03"},
   artefact={"C-209"}, owners={"HR Training Lead", "HR Systems Lead"}),
 D(106, "SMS reminders for leave approvals", "Human Resources",
   "Managers forget to approve leave requests because they only see them by email. We want an SMS reminder when a leave request waits more than two days. The SMS needs the employee mobile number from the HR system.",
   "Leave requests approved within 2 days", "Enhancement of existing", "Low", "", "2027-04-30",
   "SMS application, HR system",
   mentions={"SMS application": ["C-211"], "HR system": ["C-204"]},
   domain=["Application"], apps={"C-211", "C-204"}, classification="Confidential", security={"SC-01", "SC-03"},
   artefact={"C-211"}, owners={"Communications Systems Lead", "HR Systems Lead"}),
 D(107, "Procurement spend analytics", "Procurement",
   "We cannot see spend by vendor across departments. Purchase data sits in the procurement system and is exported to spreadsheets each month.",
   "A dashboard of spend by vendor, category and department", "Data & analytics", "Medium", "", "2027-06-30",
   "procurement system, data warehouse, purchase orders",
   mentions={"procurement system": ["C-214"], "data warehouse": ["C-205"], "purchase orders": ["DE-08"]},
   domain=["Data"], apps={"C-214", "C-205"}, classification="Internal", security={"SC-01", "SC-03"},
   artefact={"C-205"}, owners={"Procurement Systems Lead", "Head of Data Office"}),   # P-104 is the HR subject area, not procurement
 D(108, "Retire the Oracle database platform", "Information Technology",
   "The Oracle database licence ends in 2027 and costs are rising. We want to retire Oracle DB and move the systems that depend on it.",
   "No dependency on Oracle by the licence end date", "Infrastructure & platform", "High", "Licence ends 2027-06-30", "2027-06-01",
   "Oracle DB, Oracle Database 11",
   mentions={"Oracle DB": ["T-01"], "Oracle Database 11": ["T-01"]},
   domain=["Technology"], apps={"C-204", "C-207", "C-201"}, classification="Not stated", security=None,
   artefact=None, owners={"Infrastructure Services Lead", "HR Systems Lead", "Central HR Entity Lead", "Finance Systems Lead"}),
 D(109, "Move departmental file servers to cloud storage", "Information Technology",
   "Departments keep documents on on-premises file servers that are near capacity. We want to move them to cloud storage and keep search and access rights.",
   "File servers retired; documents in cloud storage with the same access rights", "Infrastructure & platform", "Medium", "File servers reach capacity in Q2 2027", "2027-05-31",
   "file servers, cloud storage, document management system",
   mentions={"file servers": ["T-02"], "cloud storage": ["T-03"], "document management system": ["C-203"]},
   domain=["Technology"], apps={"C-203"}, classification="Not stated", security=None,
   artefact={"T-03"}, owners={"Infrastructure Services Lead", "Administration Systems Lead"}),
 D(110, "Customer feedback portal", "Customer Services",
   "Customers cannot give feedback after a service. We want a feedback form linked to the customer record in the CRM and a thank-you SMS.",
   "Feedback collected for every completed service", "New solution", "Medium", "", "2027-03-15",
   "CRM, SMS application, customer data",
   mentions={"CRM": ["C-213"], "SMS application": ["C-211"], "customer data": ["DE-07"]},
   domain=["Application", "Security"], apps={"C-213", "C-211"}, classification="Confidential", security={"SC-01", "SC-03"},
   artefact={"C-213"}, owners={"Customer Experience Lead", "Communications Systems Lead"}),
 D(111, "Mobile inspection app for field inspectors", "Operations",
   "Inspectors fill paper forms on site and type them in at the office. We want a tablet app that works without a connection and uploads results.",
   "Inspection results available the same day", "New solution", "Medium", "", "2027-09-30",
   "inspection tablets, field inspection app",
   mentions={"inspection tablets": [], "field inspection app": []},
   domain=["Application"], apps=set(), classification="Not stated", security=None, artefact=None, owners=None),
 D(112, "Improve reporting", "Operations",
   "Reporting is slow and people are unhappy with it. We want it improved.",
   "Better reporting", "Other", "Low", "", "2027-12-31", "",
   mentions={}, domain=None, apps=set(), classification="Not stated", security=None, artefact=None, owners=None),
 D(113, "Peoplex payroll module and att. devices alignment", "Human Resources",
   "Attendance from the att. devices is copied into the Peoplex payroll module every month. Corrections take a week.",
   "Attendance flows to payroll without copying", "Interface between systems", "Medium", "", "2027-03-01",
   "Peoplex payroll module, att. devices",
   mentions={"Peoplex payroll module": ["C-204"], "att. devices": []},
   domain=["Application"], apps={"C-204"}, classification="Confidential", security={"SC-01", "SC-03"},
   artefact={"C-210"}, owners={"HR Systems Lead"},   # the attendance devices already feed the attendance system, which feeds Peoplex
   ask_ok_for={"Duplicate with existing artefact"}),   # an interface demand, and the knowledge base has no interface catalog: asking for it is right
 D(114, "HR analytics on the data warehouse", "Human Resources",
   "HR cannot report on headcount trends. HR data sits in the HR system and is not in the data warehouse.",
   "Headcount and leave trends available in the data warehouse", "Data & analytics", "Medium", "", "2027-06-30",
   "HR data, data warehouse, HR system",
   mentions={"HR data": ["DE-01"], "data warehouse": ["C-205"], "HR system": ["C-204"]},
   domain=["Data"], apps={"C-205", "C-204"}, classification="Confidential", security={"SC-01", "SC-03"},
   artefact={"P-104"}, owners={"Head of Data Office", "HR Systems Lead"}),

 # held-out demands, written after the first runs and used to tune nothing: another language, a misspelt name,
 # a bare ambiguous name, and data sets of different classifications moving to a platform
 D(115, "تطبيق للموظفين لطلب الإجازات", "Human Resources",
   "يقدم الموظفون طلبات الإجازة عبر البريد الإلكتروني ويعيد قسم الموارد البشرية إدخالها يدويا في Peoplex، وتتأخر الموافقات أياما. نريد تطبيقا يرسل تذكيرا برسالة SMS للمدير عند تأخر الموافقة.",
   "تتم الموافقة على طلبات الإجازة خلال يوم واحد", "New solution", "Medium", "", "2027-05-31",
   "Peoplex, SMS",
   mentions={"Peoplex": ["C-204"], "SMS": ["C-211"]},
   domain=["Application", "Security"], apps={"C-204", "C-211"}, classification="Confidential", security={"SC-01", "SC-03"},
   artefact={"C-211"}, owners={"HR Systems Lead", "Communications Systems Lead"}),
 D(116, "Leave balance display on the intranet", "Human Resources",
   "Employees cannot see their leave balance without asking HR. The balance is held in Peoplx HR and should be shown on the intranet.",
   "Employees see their leave balance online", "Enhancement of existing", "Low", "", "2027-04-15",
   "Peoplx HR, intranet",
   mentions={"Peoplx HR": ["C-204"], "intranet": ["C-216"]},
   domain=["Application", "Security"], apps={"C-204", "C-216"}, classification="Confidential", security={"SC-01", "SC-03"},
   artefact={"C-204"}, owners={"HR Systems Lead", "Communications Systems Lead"}),
 D(117, "Move payroll and employee records to cloud storage", "Information Technology",
   "Payroll data and employee records are archived on the on-premises file servers, which are near capacity. We want to move the archives to cloud storage.",
   "Archives held in cloud storage with the same access controls", "Infrastructure & platform", "Medium", "", "2027-08-31",
   "payroll data, employee records, cloud storage",
   mentions={"payroll data": ["DE-12"], "employee records": ["DE-02"], "cloud storage": ["T-03"]},
   domain=["Technology", "Security"], apps=set(), classification="Restricted", security=None,
   artefact={"T-03"}, owners={"Infrastructure Services Lead"}),
 D(118, "Payroll costing in the finance system", "Finance",
   "Payroll costs are re-keyed from HR into the finance system each month. We want HR payroll costs posted to the general ledger automatically.",
   "Payroll costs posted to the ledger without re-keying", "Interface between systems", "Medium", "", "2027-02-28",
   "HR, finance system",
   mentions={"finance system": ["C-201"], "HR": ["C-204"]},
   domain=["Application", "Security"], apps={"C-201", "C-204"}, classification="Restricted", security={"SC-01", "SC-03"},
   artefact={"C-201"}, owners={"Finance Systems Lead", "HR Systems Lead"}),
]


for _d in DEMANDS:
    _g = _d["gold"]
    if _g["classification"] in ("Confidential", "Restricted") and _g["domain"] and "Security" not in _g["domain"]:
        _g["domain"] = list(_g["domain"]) + ["Security"]


# ---- mentions step 1 cannot settle by words, for the page finder (written before the finder was run) -----------
# (mention, group it was listed in, entity ids it means; [] = the knowledge base has nothing for it)
FINDER_CASES = [
    ("staff clock-in machines", "systems", ["C-210"]),
    ("نظام الموارد البشرية", "systems", ["C-204"]),
    ("the reporting warehouse", "systems", ["C-205"]),
    ("DWH", "systems", ["C-205"]),
    ("the corporate mail system", "systems", ["C-212"]),
    ("telephony platform", "systems", ["C-202"]),
    ("company intranet site", "systems", ["C-216"]),
    ("SMS sender", "systems", ["C-211"]),
    ("قاعدة بيانات Oracle", "systems", ["T-01"]),
    ("cloud object storage", "systems", ["T-03"]),
    ("payroll", "systems", ["C-207"]),
    ("complaints log", "data", ["DE-05"]),
    ("vendor and tender data", "data", ["DE-08"]),
    ("signed agreements", "data", ["DE-06"]),
    ("SAP Ariba", "systems", []),
    ("fax machine", "systems", []),
    ("inspection tablets", "systems", []),
    ("website forms", "systems", []),
    ("Salesforce", "systems", []),
    ("blockchain ledger", "systems", []),
    ("customer satisfaction survey results", "data", []),
    ("drone imagery", "data", []),
]


def page_entries():
    """The wiki as the finder's list reads it: own pages (catalogue pages themselves left out) plus one entry per
    catalogue-only item. [{'slug', 'title', 'type', 'summary'}]"""
    sys.path.insert(0, str(ROOT / "src"))
    from eawiki.cases import pagefinder as pf
    out = [pf.page_item(slug, md) for slug, md in PAGES.items() if not slug.startswith("catalogue-")]
    out += [pf.page_item(slug, page(slug)) for slug in PAGE_REDIRECTS]
    return out
