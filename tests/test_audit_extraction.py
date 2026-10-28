"""The extraction audit: it counts what a Word or PowerPoint file holds, and finds what the extraction lost."""
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_extraction as ae  # noqa: E402

NS_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" ' \
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"'
NS_P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def wp(t):
    return f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"


def wtable(rows):
    return "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc>{wp(c)}</w:tc>" for c in r) + "</w:tr>" for r in rows) + "</w:tbl>"


def make_docx(path, body):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document {NS_W}><w:body>{body}</w:body></w:document>')
        z.writestr("word/media/image1.png", b"x")


def make_pptx(path, slides):
    with zipfile.ZipFile(path, "w") as z:
        for i, body in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld {NS_P}><p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>')


def blocks(path, items):
    path.write_text(json.dumps({"blocks": items}), encoding="utf-8")


def test_a_word_file_is_audited_for_tables_pictures_text_boxes_and_text(tmp_path):
    body = (wp("The capability model has twenty-seven level-1 capabilities.")
            + wtable([["Capability", "Owner unit", "Maturity"], ["Workforce Planning", "Corporate Services", "2 Documented"]])
            + wtable([["Objective", "Code", "Intent"], ["Raise compliance", "SO1", "Be compliant"]])
            + '<w:p><w:r><w:drawing><pic:pic/></w:drawing></w:r></w:p><w:p><w:r><w:drawing><pic:pic/></w:drawing></w:r></w:p>'
            + '<w:p><w:r><w:pict><wps:txbx><w:txbxContent>' + wp("Text box with the digital strategy statement") + '</w:txbxContent></wps:txbx></w:pict></w:r></w:p>')
    make_docx(tmp_path / "Doc.docx", body)
    blocks(tmp_path / "Doc.blocks.json", [
        {"type": "paragraph", "text": "The capability model has twenty-seven level-1 capabilities."},
        {"type": "table", "text": "| Capability | Owner unit | Maturity |\n|---|---|---|\n| Workforce Planning | Corporate Services | 2 Documented |"},
        # the second table came out as loose cells: its text is there, its rows are not
        {"type": "paragraph", "text": "Objective"}, {"type": "paragraph", "text": "Code"}, {"type": "paragraph", "text": "Intent"},
        {"type": "paragraph", "text": "Raise compliance"}, {"type": "paragraph", "text": "SO1"}, {"type": "paragraph", "text": "Be compliant"},
        {"type": "figure", "figure": {"caption": "", "image_path": "data/images/Doc-1.png"}, "description": "A heat map."},
        {"type": "figure", "figure": {"caption": "", "image_path": None}, "description": ""}])
    a = ae.audit(tmp_path / "Doc.docx", tmp_path / "Doc.blocks.json")
    assert a["source"]["tables"] == 2 and a["extracted"]["table_blocks"] == 1
    assert a["tables_kept_as_tables"] == 1 and a["tables_not_kept"] == 1 and a["tables_not_kept_first_rows"] == ["objective | code | intent"]
    assert a["source"]["pictures"] == 2 and a["extracted"]["figures"] == 2 and a["extracted"]["figures_with_image"] == 1 and a["extracted"]["figures_described"] == 1
    assert a["source"]["textboxes"] == 1 and a["text_missing"] == 1 and a["missing"][0][0] == "text box"        # the text box was not extracted
    text = ae.report(a, 5)
    assert "1 kept as tables, 1 not" in text and "table(s) lost their rows" in text and "1 figure(s) have no image file" in text
    assert "piece(s) of text were not extracted" in text


def test_a_clean_extraction_has_nothing_missing(tmp_path):
    make_docx(tmp_path / "Clean.docx", wp("A paragraph that is long enough to count.") + wtable([["Name", "Value"], ["Evaluate", "Retired service"]]))
    blocks(tmp_path / "Clean.blocks.json", [{"type": "paragraph", "text": "A paragraph that is long enough to count."},
                                            {"type": "table", "text": "| Name | Value |\n|--|--|\n| Evaluate | Retired service |"}])
    a = ae.audit(tmp_path / "Clean.docx", tmp_path / "Clean.blocks.json")
    assert a["text_missing"] == 0 and a["tables_not_kept"] == 0 and "nothing missing" in ae.report(a, 5)


def test_a_powerpoint_file_is_audited_for_slides_tables_pictures_shapes_and_groups(tmp_path):
    tbl = ('<p:graphicFrame><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl>'
           '<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Application</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>Status</a:t></a:r></a:p></a:txBody></a:tc></a:tr>'
           '<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Evaluate service</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>Not in use anymore</a:t></a:r></a:p></a:txBody></a:tc></a:tr>'
           '</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')
    shape = '<p:sp><p:txBody><a:p><a:r><a:t>Digital transformation roadmap for 2027</a:t></a:r></a:p></p:txBody></p:sp>'
    grp = '<p:grpSp><p:sp><p:txBody><a:p><a:r><a:t>Grouped box: capability map group</a:t></a:r></a:p></p:txBody></p:sp></p:grpSp>'
    make_pptx(tmp_path / "Deck.pptx", [shape + tbl + "<p:pic/>", grp])
    blocks(tmp_path / "Deck.blocks.json", [{"type": "paragraph", "text": "Digital transformation roadmap for 2027"},
                                           {"type": "table", "text": "| Application | Status |\n|--|--|\n| Evaluate service | Not in use anymore |"},
                                           {"type": "figure", "figure": {"image_path": "x.png"}, "description": "A picture."}])
    a = ae.audit(tmp_path / "Deck.pptx", tmp_path / "Deck.blocks.json")
    assert a["source"]["slides"] == 2 and a["source"]["tables"] == 1 and a["source"]["pictures"] == 1 and a["source"]["groups"] == 1
    assert a["tables_kept_as_tables"] == 1 and a["text_missing"] == 1 and "capability map group" in a["missing"][0][2]       # a shape inside a group was dropped
    assert "2 slides" not in ae.report(a, 5) and "slides 2" in ae.report(a, 5)


def test_the_script_runs_on_a_folder_and_skips_what_has_no_blocks(tmp_path, capsys, monkeypatch):
    make_docx(tmp_path / "A.docx", wp("A paragraph that is long enough to count."))
    make_docx(tmp_path / "B.docx", wp("Another paragraph that is long enough."))
    blocks(tmp_path / "A.blocks.json", [{"type": "paragraph", "text": "A paragraph that is long enough to count."}])
    monkeypatch.setattr(sys, "argv", ["audit", "--docs", str(tmp_path), "--blocks", str(tmp_path)])
    assert ae.main() == 0
    out = capsys.readouterr().out
    assert "A.docx" in out and "nothing missing" in out and "not audited: B.docx" in out
