"""Writes the input files the request chat is checked with (inputs/): a PDF of one demand, the same as a plain memo, a PDF of two, a sheet of one, a sheet of two
(the second is missing its sponsor and its go-live date, so the chat has something to ask). Needs reportlab and openpyxl; the files
are kept in the repo, so this only needs running to change them.

    python tests/e2e_request_chat/make_inputs.py
"""
from pathlib import Path

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).resolve().parent / "inputs"
OUT.mkdir(exist_ok=True)
A = {"id": "D-2026-301", "title": "Self-service payslip portal", "date": "2026-09-02", "dept": "Human Resources", "role": "Head of HR Operations",
     "sponsor": "Director of HR", "type": "New solution", "urgency": "Medium", "golive": "2027-02-28",
     "need": "Employees ask HR for payslip copies by email. HR staff retrieve each one from the payroll system and send it back by hand. This takes about two days and creates a queue every month end.",
     "outcome": "Employees download their own payslips at any time, and HR no longer handles payslip requests."}
B = {"id": "D-2026-302", "title": "Contract renewal alerts", "date": "2026-09-04", "dept": "Procurement", "role": "Procurement Manager",
     "sponsor": "Chief Procurement Officer", "type": "Enhancement of existing", "urgency": "High", "golive": "2026-12-15",
     "need": "Contract renewal dates are tracked in a spreadsheet. Two licences lapsed unnoticed last year and were bought again at a higher price.",
     "outcome": "Owners are alerted 90 days before a contract ends, and no licence lapses unnoticed."}
st = getSampleStyleSheet()


def pdf(name, demands):
    out = []
    for n, d in enumerate(demands):
        if n:
            out.append(PageBreak())
        out += [Paragraph(f"Demand request {n + 1}: {d['title']}", st["Title"])]
        out += [Paragraph(f"{k}: {d[f]}", st["Normal"]) for k, f in (("Demand ID", "id"), ("Date submitted", "date"), ("Requesting department", "dept"),
                                                                    ("Requester role", "role"), ("Business sponsor", "sponsor"))]
        out += [Spacer(1, 10), Paragraph("Business need", st["Heading2"]), Paragraph(d["need"], st["Normal"]),
                Paragraph("Expected outcome", st["Heading2"]), Paragraph(d["outcome"], st["Normal"]),
                Paragraph(f"Request type: {d['type']}. Requester urgency: {d['urgency']}. Target go-live: {d['golive']}.", st["Normal"])]
    SimpleDocTemplate(str(OUT / name), pagesize=A4, invariant=1).build(out)


def memo(name):
    """A demand as people really write one: a memo in plain sentences, with no ID and no title, the sponsor and the date inside the text."""
    out = [Paragraph("Memo: request for a supplier onboarding workflow", st["Title"]),
           Paragraph("<b>To:</b> Enterprise Architecture", st["Normal"]),
           Paragraph("<b>From:</b> Head of Supplier Management, Procurement", st["Normal"]),
           Paragraph("<b>Date:</b> 14 September 2026", st["Normal"]), Spacer(1, 12)]
    for text in (
        "We onboard about 40 new suppliers a year. Each one is handled by email: Procurement collects the company documents, Finance checks the bank "
        "details, Legal reviews the contract terms, and Information Security reviews anything that touches our data. Nobody has a single view of where a "
        "supplier is in the process, and in the last two quarters three suppliers waited more than six weeks because a document sat in someone's inbox.",
        "We would like a workflow that routes a new supplier through those four checks, shows its status to everyone involved, and reminds the owner of "
        "a step that has waited more than five working days. It should use our contract register and the finance system, which already holds the "
        "supplier bank details, so that nobody has to key them in again.",
        "The Chief Procurement Officer sponsors this request. We would like it live before the annual contract round starts in March 2027. This is a "
        "new solution. It is not urgent, but the delays hold up supplier payments."):
        out += [Paragraph(text, st["Normal"]), Spacer(1, 8)]
    SimpleDocTemplate(str(OUT / name), pagesize=A4, invariant=1).build(out)


HEAD = ["Demand ID", "Date submitted", "Requesting department", "Requester role", "Business sponsor", "Demand title", "Business need / problem",
        "Expected outcome / benefit", "Request type", "Requester urgency", "Reason for urgency / deadline", "Target go-live", "Systems or data mentioned"]


def sheet(name, demands, blank=()):
    wb = Workbook()
    ws = wb.active
    ws.append(HEAD)
    for d in demands:
        row = [d["id"], d["date"], d["dept"], d["role"], d["sponsor"], d["title"], d["need"], d["outcome"], d["type"], d["urgency"], "", d["golive"], ""]
        ws.append(["" if (d["id"], HEAD[i]) in blank else v for i, v in enumerate(row)])
    wb.save(OUT / name)


pdf("one_demand.pdf", [A])
memo("one_demand_memo.pdf")
pdf("two_demands.pdf", [A, B])
sheet("one_demand.xlsx", [A])
sheet("two_demands.xlsx", [A, B], blank={("D-2026-302", "Business sponsor"), ("D-2026-302", "Target go-live")})
print(sorted(p.name for p in OUT.iterdir()))
