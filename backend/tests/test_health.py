import pytest


@pytest.mark.django_db
def test_health_reports_ok_with_database(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_api_docs_are_not_public_outside_development(client):
    # Tests run like production (DEBUG off): the schema is exported by a command, not served to anyone.
    assert client.get("/api/openapi.json").status_code == 404
    assert client.get("/api/docs").status_code == 404


def test_openapi_schema_can_be_exported():
    from config.api import api

    assert api.get_openapi_schema()["info"]["title"] == "Grafikomat API"
