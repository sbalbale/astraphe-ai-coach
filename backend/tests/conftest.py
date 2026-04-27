import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.dependencies import get_current_athlete

# The UUID we want to return whenever the API asks for the current authenticated user
MOCK_ATHLETE_ID = "550e8400-e29b-41d4-a716-446655440000"

def override_get_current_athlete():
    """Mock authentication dependency that returns a fixed athlete ID."""
    return MOCK_ATHLETE_ID

@pytest.fixture
def client():
    """Provides a test client with bypassed authentication."""
    # Tell FastAPI to use our mock function instead of checking for a Supabase JWT
    app.dependency_overrides[get_current_athlete] = override_get_current_athlete
    
    # Yield the client so tests can use it
    with TestClient(app) as test_client:
        yield test_client
        
    # Clean up the overrides after the tests finish
    app.dependency_overrides = {}

@pytest.fixture
def test_athlete_id():
    """A standard UUID for consistent testing across modules."""
    return MOCK_ATHLETE_ID