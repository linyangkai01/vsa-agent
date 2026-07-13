"""Tests for tools/geolocation.py."""

from vsa_agent.video_analytics.nvschema import Incident, Location


def test_enrich_incidents_with_default_location_and_zone():
    from vsa_agent.tools.geolocation import enrich_incidents_with_location

    incidents = [Incident(id="1", description="intrusion", category="intrusion")]

    enriched = enrich_incidents_with_location(
        incidents,
        default_location_name="Warehouse A",
        default_zone="loading_dock",
    )

    assert enriched[0].location is not None
    assert enriched[0].location.name == "Warehouse A"
    assert enriched[0].location.zone == "loading_dock"


def test_enrich_incidents_keeps_existing_location():
    from vsa_agent.tools.geolocation import enrich_incidents_with_location

    incidents = [
        Incident(
            id="1",
            description="intrusion",
            category="intrusion",
            location=Location(name="Warehouse B", zone="gate"),
        )
    ]

    enriched = enrich_incidents_with_location(
        incidents,
        default_location_name="Warehouse A",
        default_zone="loading_dock",
    )

    assert enriched[0].location is not None
    assert enriched[0].location.name == "Warehouse B"
    assert enriched[0].location.zone == "gate"


def test_summarize_geolocation_groups_by_zone():
    from vsa_agent.tools.geolocation import summarize_geolocation

    incidents = [
        Incident(
            id="1",
            description="intrusion",
            category="intrusion",
            location=Location(name="Warehouse A", zone="loading_dock"),
        ),
        Incident(
            id="2",
            description="forklift stop",
            category="vehicle",
            location=Location(name="Warehouse A", zone="loading_dock"),
        ),
        Incident(
            id="3",
            description="person enters gate",
            category="intrusion",
            location=Location(name="Warehouse A", zone="gate"),
        ),
    ]

    summary = summarize_geolocation(incidents)

    assert "loading_dock" in summary
    assert "gate" in summary
    assert "2" in summary
