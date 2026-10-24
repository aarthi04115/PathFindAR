# PathFindAR — Unified Workspace

**PathFindAR** is an Augmented Reality (AR) indoor navigation system. It combines an ARCore mobile frontend developed with **Unity 6** and a high-performance **FastAPI** Python backend utilizing A* pathfinding over indoor topological maps.

---

## 📁 Repository Structure

- **frontend-unity/**: Unity 6 AR Foundation mobile client (Assets, Packages, ProjectSettings)
- **backend-fastapi/**: FastAPI Python routing & navigation backend (app, data, tests, pyproject.toml)
- **docs/**: System architecture, API specifications, and setup guides
- **.github/workflows/**: Continuous Integration automated testing
- **.gitignore**: Clean exclusion list for Unity Library caches and Python virtual environments
- **.env.example**: Environment variable template for backend configuration
- **CONTRIBUTING.md**: Branching strategy and team guidelines

---

## 🚀 Quick Start Guide

### 1. Backend Setup (FastAPI)

#### Prerequisites
- Python >= 3.10

#### Installation Steps (PowerShell / Terminal)
`powershell
cd backend-fastapi
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
pip install pytest httpx
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
`

#### Verifying the Backend
- Health Check: http://localhost:8000/health
- API Docs (Swagger): http://localhost:8000/docs
- Run Tests: pytest tests/

---

### 2. Frontend Setup (Unity 6 AR)

#### Prerequisites
- Unity Hub with Unity 6 (6000.3.22f1)
- Android Build Support, Android SDK/NDK, OpenJDK

#### Opening the Project
1. Open Unity Hub.
2. Click Add -> Add project from disk.
3. Select rontend-unity.
4. Open Assets/Scenes/MainARScene.unity.

#### Configuring Backend Address
- In the Unity Hierarchy, select RouteApiClient.
- In the Inspector, set Backend Url:
  - Editor Testing: http://localhost:8000
  - Physical Android Testing: http://<YOUR_PC_LAN_IP>:8000
