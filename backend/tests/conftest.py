import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    """Provides a test client for API endpoint testing."""
    return TestClient(app)

@pytest.fixture
def test_athlete_id():
    """A standard UUID for consistent testing across modules."""
    return "550e8400-e29b-41d4-a716-446655440000"