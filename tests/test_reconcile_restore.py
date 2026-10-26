"""A relation demoted only because an endpoint was `element` comes back once the endpoints are typed."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eawiki.reconcile import restore_relation  # noqa: E402

MENU = json.loads((ROOT / "data" / "togaf92_metamodel.json").read_text(encoding="utf-8"))
DEMOTED = {"relation": "associated_with",
           "note": "demoted from 'is_deployed_on' (not a valid element->element triple)"}


def test_restored_when_resolved_types_make_it_lawful():
    assert restore_relation(MENU, DEMOTED, "physical_application_component",
                            "physical_technology_component") == "is_deployed_on"


def test_stays_generic_while_an_endpoint_is_still_element():
    assert restore_relation(MENU, DEMOTED, "element", "element") == "associated_with"


def test_a_plain_generic_edge_is_left_alone():
    plain = {"relation": "associated_with"}
    assert restore_relation(MENU, plain, "physical_application_component",
                            "physical_technology_component") == "associated_with"


if __name__ == "__main__":
    test_restored_when_resolved_types_make_it_lawful()
    test_stays_generic_while_an_endpoint_is_still_element()
    test_a_plain_generic_edge_is_left_alone()
    print("ok")
