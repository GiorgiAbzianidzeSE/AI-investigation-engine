"""Guards on the synthetic corpus: every file parses, contradictions are planted, gaps stay unanswered."""
import re
from pathlib import Path

import pytest

from app.ingest.parsers import parse_file
from scripts.incident_texts import DOCUMENTS
from scripts.make_incidents import render


@pytest.fixture(scope="module")
def texts():
    return {d["filename"]: parse_file(d["filename"], render(d)).text for d in DOCUMENTS}


def test_sixteen_documents_in_four_formats(texts):
    assert len(texts) == 16
    assert {Path(f).suffix for f in texts} == {".md", ".docx", ".pdf", ".html"}


def test_long_documents(texts):
    assert len(texts["PM-2041-postmortem.pdf"].split()) >= 1200
    assert len(texts["payments-architecture.md"].split()) >= 1000


def test_contradictions_planted(texts):
    assert "3 h 40 min" in texts["INC-2041-incident-report.pdf"]
    assert "about 2 hours" in texts["status-page-march-2026.html"]
    assert "third-party card network" in texts["status-page-march-2026.html"]
    assert "fraud-scorer was not a contributing factor" in texts["PM-2041-postmortem.pdf"]
    assert "1,200 merchants" in texts["INC-2047-incident-report.pdf"]
    assert "4,500" in texts["finance-summary-march-2026.html"]
    assert "fraud-scorer | Risk Engineering" in texts["service-catalog.html"]
    assert "ML Platform team" in texts["fraud-scorer-runbook.md"]


def test_gaps_stay_open(texts):
    everything = "\n".join(texts.values()).lower()
    for absent in ("april", "euros?", "eur", "ceo", "mobile-app", "sla"):
        assert not re.search(rf"\b{absent}\b", everything), absent
    assert "Approver:\n" in texts["CHG-0314-change-request.docx"] + "\n"
    assert "reconciliation" not in texts["CHG-0327-change-request.docx"].lower()
    assert "approv" not in texts["changelog-march-2026.md"].lower().replace("approval records", "")
