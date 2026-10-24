# PathFindAR Backend

**Indoor AR Navigation — Localization & Pathfinding Server**

Backend server for the PathFindAR system. Provides real-time visual localization, A\* pathfinding, and building map management for Unity AR clients via REST API and WebSocket.

---

## Architecture

```
Unity AR Client
     │
     ├── WebSocket (/v1/ws/localize)   ← Real-time pose streaming
     ├── GET /v1/route                 ← A* pathfinding
     ├── GET /v1/map/*                 ← Building map & POIs
     └── POST /v1/ingest/frame         ← Reference frame upload
     │
┌────▼─────────────────────────────────────────┐
│              FastAPI Server                   │
│                                               │
│  ┌──────────────┐  ┌───────────────────────┐  │
│  │  Navigation   │  │   Localization        │  │
│  │  (NetworkX    │  │   Pipeline            │  │
│  │   A* + KDTree)│  │                       │  │
│  └──────────────┘  │  Preprocessing (CV2)   │  │
│                     │  → GlobalRetriever     │  │
│  ┌──────────────┐  │  → FeatureExtractor    │  │
│  │  Session      │  │  → DescriptorMatcher  │  │
│  │  Manager      │  │  → PoseEstimator      │  │
│  └──────────────┘  │  → PoseSmoother (EMA)  │  │
│                     └───────────────────────┘  │
│  ┌──────────────┐  ┌───────────────────────┐  │
│  │  Ingestion    │  │  SQLite (ref frames)  │  │
│  │  Engine       │  │  JSON  (building map) │  │
│  └──────────────┘  └───────────────────────┘  │
└────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites
- Python 3.10+
- pip

### Local Development

```bash
# 1. Clone and enter the project
cd pathfindar_backend

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Start the server (with hot-reload)
uvicorn app.main:app --reload

# 5. Open the interactive API docs
# → http://127.0.0.1:8000/docs
```

### Docker

```bash
# Production
docker compose up --build

# Development (hot-reload, mounted source)
docker compose --profile dev up --build
```

### Run Tests

```bash
pytest tests/ -v
# Currently: 57 tests, all passing
```

---

## Project Structure

```
pathfindar_backend/
├── app/
│   ├── main.py                          # FastAPI entry point + lifespan
│   ├── api/v1/endpoints/
│   │   ├── route.py                     # GET  /v1/route
│   │   ├── map.py                       # GET  /v1/map/*
│   │   ├── localize.py                  # POST /v1/localize
│   │   ├── ws_localize.py              # WS   /v1/ws/localize
│   │   └── ingestion.py                # POST /v1/ingest/*
│   ├── core/
│   │   ├── config.py                    # Pydantic settings (.env)
│   │   ├── state.py                     # App-level singletons
│   │   ├── sessions.py                  # Session tracking + floor detection
│   │   └── logging.py                   # Loguru config
│   ├── navigation/
│   │   └── pathfinder.py               # A* pathfinding (NetworkX + KDTree)
│   └── localization/
│       ├── pipeline.py                  # ML pipeline orchestrator
│       ├── preprocessing.py             # OpenCV frame preprocessing
│       ├── smoother.py                  # Adaptive EMA pose smoother
│       ├── storage.py                   # SQLite reference frame store
│       ├── ingestion.py                 # Reference frame ingestion engine
│       └── models/
│           ├── base.py                  # Abstract interfaces (Strategy pattern)
│           └── mock.py                  # Mock implementations for testing
├── data/
│   ├── building_map.json               # Sample 2-floor building graph
│   ├── reference_frames.db             # SQLite (auto-created)
│   ├── reference_images/               # Ingested JPGs
│   └── reference_features/             # Pre-computed .npz feature vectors
├── scripts/
│   └── bulk_ingest.py                  # CLI for batch reference frame upload
├── tests/                               # 57 tests across 6 files
├── Dockerfile                           # Multi-stage production build
├── docker-compose.yml                   # Production + dev profiles
└── pyproject.toml                       # Dependencies + tooling config
```

---

## API Reference

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check + service status |
| GET | `/sessions` | Active WebSocket session list |

### Navigation

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/route` | A\* pathfinding between two nodes |

**Parameters:** `start_node` (string), `destination` (string), `floor` (int)

**Example:**
```bash
curl "http://localhost:8000/v1/route?start_node=entrance&destination=toilet&floor=0"
```

**Response:**
```json
{
  "success": true,
  "waypoints": [
    {"node_id": "entrance", "position": [0,0,0], "floor": 0, "is_turn": false},
    {"node_id": "lobby", "position": [5,0,0], "floor": 0, "is_turn": true, "turn_direction": "left"},
    {"node_id": "toilet_gf", "position": [5,0,8], "floor": 0, "is_turn": false}
  ],
  "total_distance": 13.0,
  "estimated_time_sec": 10.4
}
```

### Map Discovery

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/map/info` | Building metadata (name, floors, coordinate system) |
| GET | `/v1/map/nodes` | All nodes (filterable by `?floor=0&type=room`) |
| GET | `/v1/map/pois` | Destination picker items (rooms, facilities + aliases) |
| GET | `/v1/map/node/{id}` | Single node detail |

### Localization (HTTP)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/localize` | One-shot localization from camera frame |

### Localization (WebSocket) — **Recommended**

| Endpoint | Description |
|----------|-------------|
| `ws://host:8000/v1/ws/localize` | Real-time pose streaming (~10× faster than HTTP) |

See the [WebSocket Protocol](#websocket-protocol) section below.

### Reference Frame Ingestion

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/ingest/frame` | Upload a reference image with known pose |
| GET | `/v1/ingest/stats` | Ingestion database statistics |
| GET | `/v1/ingest/frames` | List ingested frames (`?floor=0`) |
| DELETE | `/v1/ingest/frame/{id}` | Remove a reference frame |

---

## WebSocket Protocol

Connect to `ws://host:8000/v1/ws/localize`. All messages are JSON.

### Connection Handshake
On connect, the server sends:
```json
{
  "type": "connected",
  "connection_id": "ws_1",
  "nav_map_loaded": true,
  "localization_loaded": true
}
```

### Client → Server Messages

#### `localize` — Send camera frame for pose correction
```json
{
  "type": "localize",
  "image_base64": "<base64-encoded JPG>",
  "arcore_pose": {
    "position": [1.0, 0.5, 2.0],
    "rotation": [0.0, 0.0, 0.0, 1.0]
  },
  "timestamp": 1700000000.0,
  "floor": 0
}
```

#### `ping` — Keepalive
```json
{"type": "ping"}
```

#### `nearest_node` — Find closest map node (no image needed)
```json
{
  "type": "nearest_node",
  "position": [1.5, 0.0, 3.2],
  "floor": 0
}
```

#### `session_info` — Get current session stats
```json
{"type": "session_info"}
```

#### `reset_smoother` — Reset pose smoother (e.g. after teleport)
```json
{"type": "reset_smoother"}
```

### Server → Client Messages

#### `pose` — Corrected pose (response to `localize`)
```json
{
  "type": "pose",
  "pose": {
    "position": [1.02, 0.5, 2.01],
    "rotation": [0.0, 0.0, 0.0, 1.0],
    "confidence": 0.85,
    "nearest_node_id": "lobby"
  },
  "timestamp": 1700000000.0,
  "latency_ms": 12.3,
  "smoothing_alpha": 0.55
}
```

#### `pose` with floor change
When the `floor` field changes between frames, the response includes:
```json
{
  "type": "pose",
  "pose": { ... },
  "floor_changed": {
    "from": 0,
    "to": 1
  }
}
```
> **Unity devs:** When you receive `floor_changed`, update your AR scene's floor context and potentially re-request the route.

#### `nearest_node` — Closest graph node
```json
{
  "type": "nearest_node",
  "node_id": "lobby",
  "label": "Lobby",
  "node_position": [5.0, 0.0, 0.0],
  "floor": 0
}
```

#### `session_info` — Session statistics
```json
{
  "type": "session_info",
  "connection_id": "ws_1",
  "duration_sec": 45.2,
  "current_floor": 0,
  "total_frames": 120,
  "total_localizations": 98,
  "avg_confidence": 0.72,
  "floor_transitions": 1,
  "last_position": [3.2, 0.0, 5.1]
}
```

#### `error` — Validation or processing error
```json
{
  "type": "error",
  "message": "Missing 'arcore_pose' field"
}
```

---

## Typical Unity Integration Flow

```
1. App Launch
   └─ GET /v1/map/info          → Configure AR scene (floors, coord system)
   └─ GET /v1/map/pois          → Populate destination picker UI

2. User taps "Navigate to Toilet"
   └─ GET /v1/route?start_node=entrance&destination=toilet&floor=0
   └─ Draw 3D waypoint line on AR floor

3. User starts walking (continuous)
   └─ Connect WS /v1/ws/localize
   └─ Every 100ms: send { type: "localize", image_base64: ..., arcore_pose: ... }
   └─ Receive smoothed pose → update AR camera position
   └─ If floor_changed → re-request route, update AR scene

4. User arrives
   └─ Close WebSocket
```

---

## Building Map Format

The building graph is defined in `data/building_map.json`:

```json
{
  "building": {
    "name": "Sample Building",
    "floors": 2,
    "floor_height_m": 4.0,
    "coordinate_system": "unity_world"
  },
  "nodes": [
    {
      "id": "entrance",
      "label": "Main Entrance",
      "position": [0.0, 0.0, 0.0],
      "floor": 0,
      "type": "poi",
      "tags": ["entrance", "accessible"]
    }
  ],
  "edges": [
    {
      "from": "entrance",
      "to": "lobby",
      "weight": 5.0
    }
  ],
  "poi_aliases": {
    "toilet": ["toilet_gf", "toilet_f1"],
    "cafe": ["cafeteria"]
  }
}
```

**Node types:** `poi`, `room`, `corridor`, `junction`, `stairwell`, `elevator`

---

## Bulk Reference Frame Ingestion

```bash
# Generate a sample CSV template
python scripts/bulk_ingest.py --generate-template ./data/poses.csv

# Edit the CSV with your image filenames and poses
# CSV format: filename,floor,pos_x,pos_y,pos_z,rot_x,rot_y,rot_z,rot_w

# Run bulk ingestion
python scripts/bulk_ingest.py \
  --image-dir ./data/mapping_walk/ \
  --csv ./data/poses.csv
```

---

## Configuration

All settings are loaded from environment variables or `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENV` | `development` | Environment name |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DATA_PATH` | `./data` | Path to data directory |
| `MODEL_PATH` | `./models` | Path to ML model weights |
| `MAP_FILE` | `building_map.json` | Building map filename |
| `FRAME_MAX_SIZE` | `640` | Max image dimension for preprocessing |
| `BLUR_THRESHOLD` | `100.0` | Laplacian variance threshold for blur detection |
| `MAX_KEYPOINTS` | `1024` | Max keypoints per frame |
| `POSE_CONFIDENCE_THRESHOLD` | `0.3` | Min confidence to accept ML pose |

---

## ML Model Integration (Future)

The localization pipeline uses the **Strategy pattern** — all ML stages are abstract interfaces in `app/localization/models/base.py`. Currently running with mock implementations.

To integrate real models:

```python
# In app/localization/models/superpoint.py
from app.localization.models.base import FeatureExtractor

class SuperPointExtractor(FeatureExtractor):
    def load(self, model_path: str) -> None:
        self.model = torch.load(model_path)

    def extract(self, image: np.ndarray) -> FeatureSet:
        # Real SuperPoint inference
        ...
```

Then swap in `main.py`:
```python
from app.localization.models.superpoint import SuperPointExtractor
state.localization = LocalizationPipeline(
    extractor=SuperPointExtractor(),
    matcher=SuperGlueMatcher(),
    retriever=NetVLADRetriever(),
)
```

**No endpoint or test changes needed** — the interfaces stay the same.

---

## License

Internal project — PathFindAR Team
