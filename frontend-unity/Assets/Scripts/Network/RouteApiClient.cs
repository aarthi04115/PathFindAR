using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Core navigation client and UI manager for PathFindAR.
/// Connects to the FastAPI backend to fetch available POIs, request routes,
/// and guide the AR DirectionArrow along received waypoints.
/// </summary>
public class RouteApiClient : MonoBehaviour
{
    [Header("Backend Configuration")]
    [Tooltip("Base URL of the FastAPI backend server")]
    public string backendUrl = "http://192.168.31.25:8000";

    [Tooltip("Start node ID matching backend graph")]
    public string startNode = "entrance";

    [Tooltip("Destination node ID matching backend graph")]
    public string destination = "room_101";

    [Tooltip("Target floor index")]
    public int floor = 0;

    [Tooltip("Restrict route to accessible paths only")]
    public bool accessibleOnly = false;

    [Header("Navigation References & Settings")]
    [Tooltip("The NavigationTarget transform that the DirectionArrow points to")]
    public Transform targetTransform;

    [Tooltip("The AR camera representing the user's position")]
    public Transform userCameraTransform;

    [Tooltip("Distance in meters to current waypoint before advancing to next")]
    public float waypointReachThreshold = 1.5f;

    [Header("Navigation State (Live Feedback)")]
    public bool isNavigating = false;
    public bool hasArrived = false;
    public bool isLoadingRoute = false;
    public bool isLoadingPOIs = false;
    public int currentWaypointIndex = 0;
    public float distanceToCurrentWaypoint = 0f;
    public string navigationStatus = "Ready";

    [Header("Map to AR Alignment (Sample Prototype)")]
    [Tooltip("Enable explicit map-to-AR alignment (rotates and offsets sample map to match user starting position/heading)")]
    public bool enableMapToARAlignment = true;

    [Tooltip("Captured AR ground position representing the map origin (Entrance 0,0,0)")]
    public Vector3 mapOriginPosition = Vector3.zero;

    [Tooltip("Captured AR yaw rotation (degrees) representing the map's forward (+Z) corridor orientation")]
    public float mapOriginYaw = 0f;

    [Tooltip("Whether the map-to-AR alignment origin has been set")]
    public bool isMapOriginSet = false;

    [Header("Debug & User Interface")]
    [Tooltip("Display the responsive navigation UI on screen")]
    public bool showDebugHUD = true;

    [Header("Editor Navigation Simulation")]
    [InspectorName("Enable Editor Navigation Simulation")]
    [Tooltip("Enable keyboard (WASD / Arrows) simulation for navigation testing in Editor")]
    public bool enableEditorNavigationSimulation = true;

    [Tooltip("Simulated ground position of the user during editor navigation testing (XZ coordinates)")]
    public Vector3 simulatedUserPosition = Vector3.zero;

    [Tooltip("Movement speed in meters per second for editor simulation")]
    public float simulationSpeed = 3.0f;

    // Stored route data
    [HideInInspector]
    public RouteWaypoint[] waypoints;

    // Discovered POIs from backend
    [System.Serializable]
    public class POIItem
    {
        public string id;
        public string label;
        public float[] position;
        public int floor;
        public string type;
        public string[] tags;
    }

    [System.Serializable]
    public class POIListResponse
    {
        public bool success;
        public POIItem[] pois;
        public int total;
    }

    [HideInInspector]
    public List<POIItem> availablePOIs = new List<POIItem>();

    private Coroutine activeRouteCoroutine;
    private Coroutine activePOICoroutine;

    // UI state
    private bool showDestinationPicker = true;
    private Vector2 poiScrollPosition = Vector2.zero;
    private string destinationSearchFilter = "";
    private string selectedDestinationLabel = "Room 101";
    private string selectedStartLabel = "Main Entrance";

    [System.Serializable]
    public class RouteResponse
    {
        public bool success;
        public RouteWaypoint[] waypoints;
        public float total_distance;
        public float estimated_time_sec;
        public string message;
        public float latency_ms;
    }

    [System.Serializable]
    public class RouteWaypoint
    {
        public string node_id;
        public string label;
        public float[] position;
        public int floor;
        public bool is_turn;
        public string turn_direction;
    }

    void Awake()
    {
        // Auto-resolve user camera if not assigned
        if (userCameraTransform == null && Camera.main != null)
        {
            userCameraTransform = Camera.main.transform;
        }

        // Auto-resolve NavigationTarget if not assigned in Inspector
        if (targetTransform == null)
        {
            GameObject navObj = GameObject.Find("NavigationTarget");
            if (navObj != null)
            {
                targetTransform = navObj.transform;
            }
        }

#if UNITY_EDITOR
        if (enableEditorNavigationSimulation && userCameraTransform != null)
        {
            simulatedUserPosition = new Vector3(userCameraTransform.position.x, 0f, userCameraTransform.position.z);
        }
#endif

        // Ensure FloorArrowVisualizer is present for cyan floor chevron runway
        if (GetComponent<FloorArrowVisualizer>() == null)
        {
            gameObject.AddComponent<FloorArrowVisualizer>();
        }
    }

    void Start()
    {
        // Fetch available sample destinations from backend on start
        FetchAvailablePOIs();
    }

    /// <summary>
    /// Fetches the points of interest from the FastAPI backend to populate destination selection.
    /// </summary>
    public void FetchAvailablePOIs()
    {
        if (activePOICoroutine != null)
        {
            StopCoroutine(activePOICoroutine);
        }
        activePOICoroutine = StartCoroutine(GetPOIsRoutine());
    }

    private IEnumerator GetPOIsRoutine()
    {
        isLoadingPOIs = true;
        string cleanBase = string.IsNullOrEmpty(backendUrl) ? "http://192.168.31.25:8000" : backendUrl.TrimEnd('/');
        string url = $"{cleanBase}/v1/map/pois";

        Debug.Log($"[PathFindAR_Net] Fetching map POIs from: {url}");

        using (UnityWebRequest request = UnityWebRequest.Get(url))
        {
            request.timeout = 5;
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                try
                {
                    POIListResponse res = JsonUtility.FromJson<POIListResponse>(request.downloadHandler.text);
                    if (res != null && res.pois != null && res.pois.Length > 0)
                    {
                        availablePOIs = new List<POIItem>(res.pois);
                        Debug.Log($"[PathFindAR_Net] Loaded {availablePOIs.Count} POIs from backend.");
                    }
                }
                catch (System.Exception ex)
                {
                    Debug.LogWarning("[PathFindAR_Net] Could not parse POIs: " + ex.Message);
                }
            }
            else
            {
                Debug.LogWarning($"[PathFindAR_Net] Could not fetch POIs ({request.error}). Using fallback destinations.");
            }
        }

        // Fallback default list from sample map if backend is unreachable
        if (availablePOIs == null || availablePOIs.Count == 0)
        {
            availablePOIs = new List<POIItem>()
            {
                new POIItem { id = "entrance", label = "Main Entrance", floor = 0, type = "poi" },
                new POIItem { id = "reception", label = "Reception", floor = 0, type = "poi" },
                new POIItem { id = "room_101", label = "Room 101", floor = 0, type = "room" },
                new POIItem { id = "room_102", label = "Room 102", floor = 0, type = "room" },
                new POIItem { id = "room_103", label = "Room 103", floor = 0, type = "room" },
                new POIItem { id = "toilet_gf", label = "Toilets (GF)", floor = 0, type = "poi" },
                new POIItem { id = "elevator_gf", label = "Elevator (GF)", floor = 0, type = "elevator" },
                new POIItem { id = "stairwell_gf", label = "Stairwell (GF)", floor = 0, type = "stairwell" },
                new POIItem { id = "cafeteria", label = "Cafeteria", floor = 1, type = "poi" },
                new POIItem { id = "meeting_room_a", label = "Meeting Room A", floor = 1, type = "poi" },
                new POIItem { id = "room_201", label = "Room 201", floor = 1, type = "room" },
                new POIItem { id = "room_202", label = "Room 202", floor = 1, type = "room" },
                new POIItem { id = "toilet_f1", label = "Toilets (Floor 1)", floor = 1, type = "poi" }
            };
        }

        isLoadingPOIs = false;
    }

    /// <summary>
    /// Explicitly anchors the sample map's entrance (0,0,0) and forward axis (+Z) to the user's current AR ground pose and heading.
    /// </summary>
    public void SetMapOriginFromCurrentPose()
    {
        Vector3 userPos = Camera.main != null ? Camera.main.transform.position : Vector3.zero;
#if UNITY_EDITOR
        if (enableEditorNavigationSimulation)
        {
            userPos = simulatedUserPosition;
        }
#endif
        mapOriginPosition = new Vector3(userPos.x, 0f, userPos.z);

        Transform cam = Camera.main != null ? Camera.main.transform : transform;
        Vector3 camFwd = cam.forward;
        camFwd.y = 0f;
        if (camFwd.sqrMagnitude > 0.001f)
        {
            camFwd.Normalize();
            mapOriginYaw = Quaternion.LookRotation(camFwd, Vector3.up).eulerAngles.y;
        }
        else
        {
            mapOriginYaw = 0f;
        }

        isMapOriginSet = true;
        Debug.Log($"[PathFindAR_Align] Map origin aligned to: {mapOriginPosition}, Heading: {mapOriginYaw:F1}°");

        // Refresh active target transform if currently navigating
        if (isNavigating && waypoints != null && currentWaypointIndex < waypoints.Length)
        {
            SetTargetToWaypoint(currentWaypointIndex);
        }
    }

    /// <summary>
    /// Resets the map-to-AR alignment to the raw Unity world origin.
    /// </summary>
    public void ResetMapOrigin()
    {
        mapOriginPosition = Vector3.zero;
        mapOriginYaw = 0f;
        isMapOriginSet = false;
        Debug.Log("[PathFindAR_Align] Map-to-AR alignment reset to Identity.");

        if (isNavigating && waypoints != null && currentWaypointIndex < waypoints.Length)
        {
            SetTargetToWaypoint(currentWaypointIndex);
        }
    }

    /// <summary>
    /// Transforms a sample-map coordinate [x, y, z] into the aligned AR coordinate space.
    /// Keeps horizontal (X, Z) aligned with the user-confirmed origin/heading while leaving
    /// vertical floor elevation handling separate.
    /// </summary>
    public Vector3 TransformMapPointToAR(Vector3 mapPoint)
    {
        if (!enableMapToARAlignment || !isMapOriginSet)
        {
            return mapPoint;
        }

        // Rotate map point around Y axis by the aligned yaw heading
        Quaternion rot = Quaternion.Euler(0f, mapOriginYaw, 0f);
        Vector3 rotatedOffset = rot * new Vector3(mapPoint.x, 0f, mapPoint.z);

        // Translate by the aligned ground origin
        Vector3 aligned = mapOriginPosition + rotatedOffset;
        aligned.y = mapPoint.y; // Preserve map relative floor height separately
        return aligned;
    }

    /// <summary>
    /// Starts navigation toward the selected destination.
    /// </summary>
    public void StartNavigation()
    {
        if (isLoadingRoute) return;

        if (string.IsNullOrEmpty(destination))
        {
            navigationStatus = "Please select a destination first.";
            return;
        }

        if (startNode == destination)
        {
            navigationStatus = "Start and destination cannot be identical.";
            return;
        }

        showDestinationPicker = false;
        RequestRoute();
    }

    /// <summary>
    /// Cancels active navigation and returns to destination selection.
    /// </summary>
    public void StopNavigation()
    {
        if (activeRouteCoroutine != null)
        {
            StopCoroutine(activeRouteCoroutine);
        }

        isNavigating = false;
        hasArrived = false;
        isLoadingRoute = false;
        waypoints = null;
        currentWaypointIndex = 0;
        navigationStatus = "Navigation cancelled.";
        showDestinationPicker = true;
    }

    public void RequestRoute()
    {
        if (isLoadingRoute) return;

        Debug.Log("[PathFindAR_Net] RequestRoute() entered. Starting route request coroutine.");
        if (activeRouteCoroutine != null)
        {
            StopCoroutine(activeRouteCoroutine);
        }
        activeRouteCoroutine = StartCoroutine(GetRoute());
    }

    private IEnumerator GetRoute()
    {
        isLoadingRoute = true;
        Debug.Log("[PathFindAR_Net] GetRoute() began.");

        // Guard against missing NavigationTarget
        if (targetTransform == null)
        {
            GameObject navObj = GameObject.Find("NavigationTarget");
            if (navObj != null)
            {
                targetTransform = navObj.transform;
            }
            else
            {
                navigationStatus = "Error: NavigationTarget GameObject not found!";
                Debug.LogError("[PathFindAR_Net] " + navigationStatus);
                isLoadingRoute = false;
                yield break;
            }
        }

        // Fallback user camera
        if (userCameraTransform == null && Camera.main != null)
        {
            userCameraTransform = Camera.main.transform;
        }

        string cleanBase = string.IsNullOrEmpty(backendUrl) ? "http://192.168.31.25:8000" : backendUrl.TrimEnd('/');
        string url = $"{cleanBase}/v1/route?start_node={UnityWebRequest.EscapeURL(startNode)}" +
                     $"&destination={UnityWebRequest.EscapeURL(destination)}" +
                     $"&floor={floor}" +
                     $"&accessible_only={accessibleOnly.ToString().ToLower()}";

        Debug.Log($"[PathFindAR_Net] Final URL constructed: {url}");

        navigationStatus = "Requesting route...";

        using (UnityWebRequest request = UnityWebRequest.Get(url))
        {
            request.timeout = 10;
            Debug.Log($"[PathFindAR_Net] SendWebRequest() begins for: {url} (Timeout: {request.timeout}s)...");

            yield return request.SendWebRequest();

            isLoadingRoute = false;

            if (request.result != UnityWebRequest.Result.Success)
            {
                navigationStatus = $"Connection Failed (HTTP {request.responseCode}): {request.error}";
                Debug.LogError($"[PathFindAR_Net] ROUTE REQUEST FAILED ({url}): HTTP {request.responseCode} - {request.error}\nResponse: {request.downloadHandler?.text}");
                isNavigating = false;
                yield break;
            }

            string json = request.downloadHandler.text;
            Debug.Log($"[PathFindAR_Net] Route JSON successfully received (HTTP {request.responseCode}):\n" + json);

            RouteResponse route = null;
            try
            {
                route = JsonUtility.FromJson<RouteResponse>(json);
            }
            catch (System.Exception ex)
            {
                navigationStatus = "JSON Parse Error";
                Debug.LogError("Could not parse route JSON: " + ex.Message);
                isNavigating = false;
                yield break;
            }

            if (route == null || !route.success)
            {
                navigationStatus = route != null ? $"Backend Error: {route.message}" : "Error: Null route parsed";
                Debug.LogError(navigationStatus);
                isNavigating = false;
                yield break;
            }

            if (route.waypoints == null || route.waypoints.Length == 0)
            {
                navigationStatus = "Error: Route contains no waypoints";
                Debug.LogError(navigationStatus);
                isNavigating = false;
                yield break;
            }

            // Store complete waypoints list
            waypoints = route.waypoints;
            currentWaypointIndex = waypoints.Length > 1 ? 1 : 0;
            hasArrived = false;
            isNavigating = true;
            navigationStatus = $"Navigating to {selectedDestinationLabel}";

            Debug.Log($"PathFindAR: Loaded {waypoints.Length} waypoints. Distance: {route.total_distance:F1}m, Est Time: {route.estimated_time_sec:F1}s");
            SetTargetToWaypoint(currentWaypointIndex);
        }
    }

    void Update()
    {
        if (!isNavigating || hasArrived || waypoints == null || waypoints.Length == 0)
        {
            return;
        }

        if (targetTransform == null)
        {
            return;
        }

#if UNITY_EDITOR
        if (enableEditorNavigationSimulation)
        {
            float horizontal = 0f;
            float vertical = 0f;

            if (Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow)) vertical += 1f;
            if (Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow)) vertical -= 1f;
            if (Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow)) horizontal += 1f;
            if (Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow)) horizontal -= 1f;

            if (horizontal != 0f || vertical != 0f)
            {
                Vector3 moveDir = new Vector3(horizontal, 0f, vertical).normalized;
                simulatedUserPosition += moveDir * (simulationSpeed * Time.deltaTime);
            }
        }

        Vector3 userPos = enableEditorNavigationSimulation
            ? simulatedUserPosition
            : (userCameraTransform != null ? userCameraTransform.position : transform.position);
#else
        Vector3 userPos = userCameraTransform != null ? userCameraTransform.position : transform.position;
#endif
        Vector3 targetPos = targetTransform.position;

        // Planar (horizontal XZ) distance to current waypoint
        userPos.y = 0f;
        targetPos.y = 0f;
        distanceToCurrentWaypoint = Vector3.Distance(userPos, targetPos);

        // Check proximity threshold to advance
        if (distanceToCurrentWaypoint <= waypointReachThreshold)
        {
            if (currentWaypointIndex < waypoints.Length - 1)
            {
                currentWaypointIndex++;
                SetTargetToWaypoint(currentWaypointIndex);
            }
            else
            {
                hasArrived = true;
                isNavigating = false;
                navigationStatus = $"★ Arrived at {waypoints[currentWaypointIndex].label}! ★";
                Debug.Log($"PathFindAR: ARRIVAL DETECTED at destination ({waypoints[currentWaypointIndex].label})!");
            }
        }
    }

    private void SetTargetToWaypoint(int index)
    {
        if (waypoints == null || index < 0 || index >= waypoints.Length)
        {
            return;
        }

        RouteWaypoint wp = waypoints[index];
        if (wp.position != null && wp.position.Length >= 3)
        {
            Vector3 rawMapPos = new Vector3(wp.position[0], wp.position[1], wp.position[2]);
            Vector3 alignedARPos = TransformMapPointToAR(rawMapPos);
            targetTransform.position = alignedARPos;

            navigationStatus = $"Step {index + 1}/{waypoints.Length}: heading toward {wp.label}";
            Debug.Log($"PathFindAR: Target updated to Waypoint [{index}] '{wp.label}' at Map: {rawMapPos} -> AR: {alignedARPos}");
        }
    }

    private bool hasLoggedOnGUI = false;

    void OnGUI()
    {
        if (!showDebugHUD) return;

        if (!hasLoggedOnGUI)
        {
            hasLoggedOnGUI = true;
            Debug.Log($"[PathFindAR_UI] OnGUI() is active ({Screen.width}x{Screen.height}).");
        }

        GUI.color = new Color(1f, 1f, 1f, 0.96f);

        float btnHeight = Application.isMobilePlatform ? 44f : 30f;
        float boxWidth = Application.isMobilePlatform ? Mathf.Min(Screen.width - 40f, 420f) : 380f;

        // 1. Destination Selection Screen (when not actively navigating or upon user request)
        if (showDestinationPicker && !isNavigating)
        {
            float pickerHeight = Application.isMobilePlatform ? Mathf.Min(Screen.height - 80f, 540f) : 460f;
            GUILayout.BeginArea(new Rect(20, 20, boxWidth, pickerHeight), GUI.skin.box);

            GUILayout.Label("<size=16><b>PathFindAR</b></size> <color=grey>Indoor Navigation</color>");
            GUILayout.Space(4);

            // Starting location
            GUILayout.Label($"<b>From:</b> <color=cyan>{selectedStartLabel}</color> (Floor {floor})");

            GUILayout.Space(2);
            // Search filter
            GUILayout.BeginHorizontal();
            GUILayout.Label("Search:", GUILayout.Width(55));
            destinationSearchFilter = GUILayout.TextField(destinationSearchFilter, GUILayout.Height(btnHeight - 8));
            if (!string.IsNullOrEmpty(destinationSearchFilter) && GUILayout.Button("X", GUILayout.Width(30), GUILayout.Height(btnHeight - 8)))
            {
                destinationSearchFilter = "";
            }
            GUILayout.EndHorizontal();

            GUILayout.Space(2);
            GUILayout.Label($"<b>Select Destination:</b> <color=yellow>{selectedDestinationLabel}</color>");

            // Scrollable POI list
            float scrollHeight = pickerHeight - 210f;
            poiScrollPosition = GUILayout.BeginScrollView(poiScrollPosition, GUILayout.Height(scrollHeight));

            string filterLower = destinationSearchFilter.Trim().ToLower();
            foreach (var poi in availablePOIs)
            {
                if (poi.id == startNode) continue; // Don't list start as destination

                if (!string.IsNullOrEmpty(filterLower))
                {
                    bool match = poi.label.ToLower().Contains(filterLower) || poi.id.ToLower().Contains(filterLower);
                    if (!match) continue;
                }

                string poiBtnText = $"{poi.label}  [Floor {poi.floor}]";
                if (poi.id == destination)
                {
                    poiBtnText = "● " + poiBtnText;
                }

                if (GUILayout.Button(poiBtnText, GUILayout.Height(btnHeight)))
                {
                    destination = poi.id;
                    selectedDestinationLabel = poi.label;
                }
            }
            GUILayout.EndScrollView();

            // Alignment status & controls
            GUILayout.Space(2);
            GUILayout.BeginHorizontal();
            string alignStatusText = isMapOriginSet ? "<color=lime>Map Aligned</color>" : "<color=orange>Map Unaligned</color>";
            GUILayout.Label($"<b>Status:</b> {alignStatusText}", GUILayout.Width(130));
            if (GUILayout.Button(isMapOriginSet ? "Re-Align" : "Align to Here", GUILayout.Height(btnHeight - 10)))
            {
                SetMapOriginFromCurrentPose();
            }
            if (isMapOriginSet && GUILayout.Button("Reset", GUILayout.Width(50), GUILayout.Height(btnHeight - 10)))
            {
                ResetMapOrigin();
            }
            GUILayout.EndHorizontal();

            GUILayout.Space(4);

            if (isLoadingRoute)
            {
                GUILayout.Label("<color=yellow><b>Calculating route... please wait</b></color>");
            }
            else
            {
                if (GUILayout.Button($"<b>Start Navigation to {selectedDestinationLabel}</b>", GUILayout.Height(btnHeight + 6)))
                {
                    if (!isMapOriginSet)
                    {
                        // Auto-anchor to user's starting spot and forward view if not explicitly pressed
                        SetMapOriginFromCurrentPose();
                    }
                    StartNavigation();
                }
            }

            if (!string.IsNullOrEmpty(navigationStatus) && navigationStatus != "Ready")
            {
                GUILayout.Label($"<color=orange>{navigationStatus}</color>");
            }

            GUILayout.EndArea();
            return;
        }

        // 2. Active Navigation HUD (Compact floating card during live AR navigation)
        float navCardHeight = enableEditorNavigationSimulation ? 270f : 210f;
        if (hasArrived) navCardHeight += 40f;

        GUILayout.BeginArea(new Rect(20, 20, boxWidth, navCardHeight), GUI.skin.box);
        GUILayout.Label($"<size=15><b>PathFindAR:</b> {selectedDestinationLabel}</size>");
        GUILayout.Space(2);

        GUILayout.Label($"<b>Status:</b> {navigationStatus}");

#if UNITY_EDITOR
        if (enableEditorNavigationSimulation)
        {
            GUILayout.Label($"<b>Simulated User:</b> ({simulatedUserPosition.x:F1}, {simulatedUserPosition.z:F1}) <color=cyan>[WASD Keys]</color>");
        }
#endif

        if (isNavigating && waypoints != null && currentWaypointIndex < waypoints.Length)
        {
            RouteWaypoint current = waypoints[currentWaypointIndex];
            GUILayout.Label($"<b>Target:</b> {currentWaypointIndex + 1}/{waypoints.Length} - {current.label}");
            GUILayout.Label($"<b>Distance:</b> {distanceToCurrentWaypoint:F1} m (advances at {waypointReachThreshold:F1} m)");

            if (current.is_turn && !string.IsNullOrEmpty(current.turn_direction))
            {
                GUILayout.Label($"<b>Turn:</b> <color=yellow>TURN {current.turn_direction.ToUpper()}</color>");
            }
        }
        else if (hasArrived)
        {
            GUILayout.Label("<color=lime><b>★ DESTINATION REACHED ★</b></color>");
            GUILayout.Label($"You have arrived safely at {selectedDestinationLabel}.");
        }

        GUILayout.Space(6);
        GUILayout.BeginHorizontal();

        if (hasArrived)
        {
            if (GUILayout.Button("Pick New Destination", GUILayout.Height(btnHeight)))
            {
                StopNavigation();
            }
        }
        else if (isNavigating)
        {
            if (GUILayout.Button("End Route", GUILayout.Height(btnHeight)))
            {
                StopNavigation();
            }
            if (GUILayout.Button("Recalculate", GUILayout.Height(btnHeight)))
            {
                RequestRoute();
            }
        }
        else
        {
            if (GUILayout.Button("Back to Menu", GUILayout.Height(btnHeight)))
            {
                showDestinationPicker = true;
            }
            if (GUILayout.Button("Retry Route", GUILayout.Height(btnHeight)))
            {
                RequestRoute();
            }
        }

#if UNITY_EDITOR
        if (enableEditorNavigationSimulation && GUILayout.Button("Reset Pos", GUILayout.Height(btnHeight)))
        {
            simulatedUserPosition = Vector3.zero;
        }
#endif
        GUILayout.EndHorizontal();

        GUILayout.EndArea();
    }
}
