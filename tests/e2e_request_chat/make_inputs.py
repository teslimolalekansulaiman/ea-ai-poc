"""Writes the input files the request chat is checked with (inputs/): a PDF of one demand, a PDF of two, a sheet of one, a sheet of two
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
    SimpleDocTemplate(str(OUT / name), pagesize=A4).build(out)


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
pdf("two_demands.pdf", [A, B])
sheet("one_demand.xlsx", [A])
sheet("two_demands.xlsx", [A, B], blank={("D-2026-302", "Business sponsor"), ("D-2026-302", "Target go-live")})
print(sorted(p.name for p in OUT.iterdir()))
