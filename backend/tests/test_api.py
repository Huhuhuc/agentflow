import os
import time

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
        exec_id = execution.json()["id"]
        # inline 模式下执行在后台任务中完成，轮询直到终态
        for _ in range(50):
            detail = client.get(f"/api/v1/executions/{exec_id}", headers=headers).json()
            if detail["status"] in ("success", "failed"):
                break
            time.sleep(0.1)
        assert detail["status"] == "success"
        assert len(detail["logs"]) >= 5

