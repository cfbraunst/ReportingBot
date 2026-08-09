"""Tests for modal filling. Uses fakes shaped like the real modal from discovery."""
import pytest

from reporter.reporter_client import Reporter, ReporterStopped
from reporter.config import REPORT_REASON
from reporter.jobs import ReportJob


class FakeInput:
    def __init__(self, custom_id):
        self.custom_id = custom_id
        self.value = None


class FakeRow:
    def __init__(self, *children):
        self.children = list(children)


class FakeModal:
    """Mirrors the real form: five inputs, each in its own row."""
    def __init__(self, ids=None):
        ids = ids or [
            "username_input", "steam64id_input",
            "server_input", "reason_input", "evidence_input",
        ]
        self.components = [FakeRow(FakeInput(i)) for i in ids]

    def inputs(self):
        return {c.custom_id: c for row in self.components for c in row.children}


@pytest.fixture
def filler():
    # _fill needs no connection, so bypass __init__'s client setup.
    return Reporter.__new__(Reporter)


@pytest.fixture
def job():
    return ReportJob(
        steam_id64=76561198012345678,
        steam_name="SomePlayer",
        server_name="Rustoria EU Long",
        requester_id=1,
        channel_id=2,
    )


def test_fills_every_field(filler, job):
    modal = FakeModal()
    filler._fill(modal, job)
    got = modal.inputs()
    assert got["username_input"].value == "SomePlayer"
    assert got["steam64id_input"].value == "76561198012345678"
    assert got["server_input"].value == "Rustoria EU Long"
    assert got["reason_input"].value == REPORT_REASON


def test_evidence_left_empty(filler, job):
    modal = FakeModal()
    filler._fill(modal, job)
    assert modal.inputs()["evidence_input"].value == ""


def test_truncates_long_username(filler, job):
    job.steam_name = "x" * 120
    modal = FakeModal()
    filler._fill(modal, job)
    assert len(modal.inputs()["username_input"].value) == 50


def test_truncates_long_custom_server(filler, job):
    job.server_name = "y" * 120
    modal = FakeModal()
    filler._fill(modal, job)
    assert len(modal.inputs()["server_input"].value) == 50


def test_halts_if_a_required_field_vanishes(filler, job):
    # If the ticket tool is reconfigured, stop rather than submit garbage.
    modal = FakeModal(ids=["username_input", "steam64id_input", "server_input"])
    with pytest.raises(ReporterStopped, match="reason_input"):
        filler._fill(modal, job)


def test_works_without_evidence_field(filler, job):
    # Evidence is optional; its absence must not break the fill.
    modal = FakeModal(ids=[
        "username_input", "steam64id_input", "server_input", "reason_input",
    ])
    filler._fill(modal, job)
    assert modal.inputs()["reason_input"].value == REPORT_REASON
