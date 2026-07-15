import os

os.environ["DATABASE_URL"] = "sqlite:///./test-agentflow.db"

from fastapi.testclient import TestClient

from app.main import app


def test_login_and_execute_demo_workflow():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": "demo@agentflow.dev", "password": "demo1234"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        workflows = client.get("/api/v1/workflows", headers=headers)
        assert workflows.status_code == 200
        workflow_id = workflows.json()[0]["id"]
        execution = client.post(f"/api/v1/workflows/{workflow_id}/execute", headers=headers, json={"input_data": {"message": "企业版怎么使用？"}})
        assert execution.status_code == 200
        assert execution.json()["status"] == "success"
        assert len(execution.json()["logs"]) >= 5

