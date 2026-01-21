"""
Health check tests for HomePilot backend API
Tests basic endpoint availability and functionality
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestHealthEndpoints:
    """Test health and basic API endpoints"""
    
    def test_health_endpoint(self):
        """Test /health endpoint returns 200"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "service" in data
        assert "version" in data
        
    def test_providers_endpoint(self):
        """Test /providers endpoint returns available providers"""
        response = client.get("/providers")
        assert response.status_code == 200
        data = response.json()
        assert "ok" in data
        assert "providers" in data
        assert isinstance(data["providers"], dict)
        
    def test_projects_list_endpoint(self):
        """Test /projects endpoint returns project list"""
        response = client.get("/projects")
        # May return 401 if API key required, or 200 if not
        assert response.status_code in [200, 401]
        if response.status_code == 200:
            data = response.json()
            assert "ok" in data
            assert "projects" in data
            
    def test_projects_examples_endpoint(self):
        """Test /projects/examples returns example templates"""
        response = client.get("/projects/examples")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "examples" in data
        assert isinstance(data["examples"], list)
        # Should have at least the 4 default examples
        assert len(data["examples"]) >= 4
        
    def test_conversations_endpoint(self):
        """Test /conversations endpoint"""
        response = client.get("/conversations")
        assert response.status_code in [200, 401]
        if response.status_code == 200:
            data = response.json()
            assert "ok" in data
            assert "conversations" in data


class TestProjectCreation:
    """Test project creation functionality"""
    
    def test_create_project_from_example(self):
        """Test creating a project from an example template"""
        # First, get available examples
        examples_response = client.get("/projects/examples")
        assert examples_response.status_code == 200
        examples = examples_response.json()["examples"]
        assert len(examples) > 0
        
        # Try to create from first example
        example_id = examples[0]["id"]
        response = client.post(f"/projects/from-example/{example_id}")
        
        # May require API key
        assert response.status_code in [200, 201, 401]
        
        if response.status_code in [200, 201]:
            data = response.json()
            assert data["ok"] is True
            assert "project" in data
            assert data["project"]["name"] == examples[0]["name"]
            

class TestAPIStructure:
    """Test API response structure and data types"""
    
    def test_health_response_structure(self):
        """Verify health endpoint returns correct structure"""
        response = client.get("/health")
        data = response.json()

        assert isinstance(data, dict)
        assert isinstance(data["ok"], bool)
        assert isinstance(data["service"], str)
        assert isinstance(data["version"], str)
        
    def test_examples_response_structure(self):
        """Verify examples endpoint returns correct structure"""
        response = client.get("/projects/examples")
        data = response.json()
        
        examples = data["examples"]
        if len(examples) > 0:
            example = examples[0]
            assert "id" in example
            assert "name" in example
            assert "description" in example
            assert "instructions" in example
            assert "icon" in example
            assert "icon_color" in example
