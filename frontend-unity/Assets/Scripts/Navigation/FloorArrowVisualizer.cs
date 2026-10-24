using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;

/// <summary>
/// FloorArrowVisualizer:
/// Renders a continuous, flowing runway of vibrant cyan chevron arrows along the active corridor floor path.
/// Connects the user's current ground position through upcoming waypoints.
/// Completely independent from the floating direction arrow so it can be toggled or tuned without side effects.
/// </summary>
public class FloorArrowVisualizer : MonoBehaviour
{
    [Header("Feature Toggles")]
    [Tooltip("Enable or disable floor chevron visualization")]
    public bool enableFloorChevrons = true;

    [Tooltip("Clean camera view: Hides the blue plane mesh while keeping AR floor tracking fully functional")]
    public bool hidePlaneMeshVisualizer = true;

    [Tooltip("Animate chevrons with a subtle forward pulse to indicate travel direction")]
    public bool animatePulse = true;

    [Header("References")]
    [Tooltip("RouteApiClient reference containing the active route waypoints")]
    public RouteApiClient routeApiClient;

    [Tooltip("AR Plane Manager for querying detected floor height")]
    public ARPlaneManager planeManager;

    [Header("Visual Styling")]
    [Tooltip("Primary glowing cyan color for floor chevrons")]
    public Color chevronColor = new Color(0f, 0.95f, 1f, 0.95f);

    [Tooltip("Continuous spacing in meters between chevrons along the corridor")]
    public float chevronSpacing = 0.65f;

    [Tooltip("Scale of each floor chevron (width, thickness, length)")]
    public Vector3 chevronScale = new Vector3(0.42f, 0.02f, 0.42f);

    [Tooltip("Vertical height offset above floor to prevent z-fighting")]
    public float floorHeightOffset = 0.025f;

    [Tooltip("Total preview distance ahead of the user along the path (in meters)")]
    public float previewDistance = 12.0f;

    [Tooltip("Pulse animation speed")]
    public float pulseSpeed = 2.5f;

    private List<GameObject> activeChevrons = new List<GameObject>();
    private Material chevronMaterial;
    private Mesh chevronMesh;
    private float cachedFloorY = 0f;
    private bool hasDetectedFloor = false;
    private float pulseTime = 0f;

    void Awake()
    {
        if (routeApiClient == null)
        {
            routeApiClient = FindFirstObjectByType<RouteApiClient>();
        }

        if (planeManager == null)
        {
            planeManager = FindFirstObjectByType<ARPlaneManager>();
        }

        CreateChevronMaterialAndMesh();
    }

    void Start()
    {
        UpdatePlaneVisibility();
    }

    void Update()
    {
        UpdatePlaneVisibility();

        if (animatePulse)
        {
            pulseTime += Time.deltaTime * pulseSpeed;
        }

        if (!enableFloorChevrons || routeApiClient == null || !routeApiClient.isNavigating || routeApiClient.waypoints == null || routeApiClient.waypoints.Length == 0)
        {
            ClearChevrons();
            return;
        }

        UpdateFloorElevation();
        BuildContinuousChevronPath();
    }

    void OnDisable()
    {
        ClearChevrons();
    }

    private void CreateChevronMaterialAndMesh()
    {
        // Try Universal Render Pipeline unlit, then Unlit/Color, then Standard
        Shader shader = Shader.Find("Universal Render Pipeline/Unlit");
        if (shader == null) shader = Shader.Find("Unlit/Color");
        if (shader == null) shader = Shader.Find("Standard");

        chevronMaterial = new Material(shader);
        chevronMaterial.color = chevronColor;
        if (chevronMaterial.HasProperty("_BaseColor"))
        {
            chevronMaterial.SetColor("_BaseColor", chevronColor);
        }

        // Standard Unity cube mesh for wing segments
        GameObject primitive = GameObject.CreatePrimitive(PrimitiveType.Cube);
        MeshFilter mf = primitive.GetComponent<MeshFilter>();
        if (mf != null)
        {
            chevronMesh = mf.sharedMesh;
        }
        Destroy(primitive);
    }

    public void UpdatePlaneVisibility()
    {
        if (planeManager == null) return;

        foreach (var plane in planeManager.trackables)
        {
            MeshRenderer mr = plane.GetComponent<MeshRenderer>();
            if (mr != null)
            {
                mr.enabled = !hidePlaneMeshVisualizer;
            }
            ARPlaneMeshVisualizer visualizer = plane.GetComponent<ARPlaneMeshVisualizer>();
            if (visualizer != null)
            {
                visualizer.enabled = !hidePlaneMeshVisualizer;
            }
        }
    }

    private void UpdateFloorElevation()
    {
        if (planeManager != null && planeManager.trackables.count > 0)
        {
            Transform cam = Camera.main != null ? Camera.main.transform : transform;
            float camY = cam.position.y;
            float bestFloorY = float.MinValue;
            bool found = false;

            foreach (var plane in planeManager.trackables)
            {
                if (plane.alignment == UnityEngine.XR.ARSubsystems.PlaneAlignment.HorizontalUp)
                {
                    float py = plane.transform.position.y;
                    if (py < camY && py > bestFloorY)
                    {
                        bestFloorY = py;
                        found = true;
                    }
                }
            }

            if (found)
            {
                cachedFloorY = bestFloorY;
                hasDetectedFloor = true;
            }
        }

        if (!hasDetectedFloor)
        {
            if (Application.isEditor)
            {
                cachedFloorY = 0f;
            }
            else if (Camera.main != null)
            {
                cachedFloorY = Camera.main.transform.position.y - 1.35f;
            }
        }
    }

    /// <summary>
    /// Builds a multi-segment continuous pathway of chevrons along the corridor.
    /// Traverses from the user ground position to the active waypoint, and continues through
    /// upcoming waypoints up to previewDistance.
    /// </summary>
    private void BuildContinuousChevronPath()
    {
        Vector3 userPos = Camera.main != null ? Camera.main.transform.position : Vector3.zero;
#if UNITY_EDITOR
        if (routeApiClient.enableEditorNavigationSimulation)
        {
            userPos = routeApiClient.simulatedUserPosition;
        }
#endif

        int currentIndex = routeApiClient.currentWaypointIndex;
        if (currentIndex < 0 || currentIndex >= routeApiClient.waypoints.Length)
        {
            ClearChevrons();
            return;
        }

        // Construct continuous route polyline from user position onward
        List<Vector3> pathPoints = new List<Vector3>();
        pathPoints.Add(new Vector3(userPos.x, cachedFloorY, userPos.z));

        for (int i = currentIndex; i < routeApiClient.waypoints.Length; i++)
        {
            var wp = routeApiClient.waypoints[i];
            if (wp.position != null && wp.position.Length >= 3)
            {
                Vector3 rawMapPos = new Vector3(wp.position[0], wp.position[1], wp.position[2]);
                Vector3 alignedPos = routeApiClient.TransformMapPointToAR(rawMapPos);
                // Keep horizontal (X, Z) aligned while resting on locally detected floor Y
                pathPoints.Add(new Vector3(alignedPos.x, cachedFloorY, alignedPos.z));
            }
        }

        if (pathPoints.Count < 2)
        {
            ClearChevrons();
            return;
        }

        // Calculate sample placements along the polyline up to previewDistance
        List<Vector3> chevronPositions = new List<Vector3>();
        List<Quaternion> chevronRotations = new List<Quaternion>();

        float distanceBudget = previewDistance;
        float accumulatedDist = 0.35f; // Small lead offset ahead of user

        for (int seg = 0; seg < pathPoints.Count - 1; seg++)
        {
            Vector3 segStart = pathPoints[seg];
            Vector3 segEnd = pathPoints[seg + 1];
            Vector3 segDir = segEnd - segStart;
            float segLength = segDir.magnitude;

            if (segLength < 0.05f) continue;
            segDir.Normalize();
            Quaternion segRot = Quaternion.LookRotation(segDir, Vector3.up);

            float currentSegPos = accumulatedDist;
            while (currentSegPos < segLength && chevronPositions.Count < 25)
            {
                Vector3 pt = segStart + segDir * currentSegPos;
                pt.y = cachedFloorY + floorHeightOffset;
                chevronPositions.Add(pt);
                chevronRotations.Add(segRot);

                currentSegPos += chevronSpacing;
                distanceBudget -= chevronSpacing;
                if (distanceBudget <= 0f) break;
            }

            accumulatedDist = currentSegPos - segLength;
            if (distanceBudget <= 0f) break;
        }

        // Adjust pooled GameObjects to match required chevron count
        int needed = chevronPositions.Count;
        while (activeChevrons.Count < needed)
        {
            activeChevrons.Add(CreateChevronObject());
        }
        while (activeChevrons.Count > needed)
        {
            int last = activeChevrons.Count - 1;
            Destroy(activeChevrons[last]);
            activeChevrons.RemoveAt(last);
        }

        // Position and orient each chevron
        for (int i = 0; i < needed; i++)
        {
            GameObject chev = activeChevrons[i];
            chev.SetActive(true);
            chev.transform.position = chevronPositions[i];
            chev.transform.rotation = chevronRotations[i];

            if (animatePulse)
            {
                // Dynamic forward flow wave effect
                float wave = Mathf.Sin(pulseTime - (i * 0.45f));
                float scaleMod = 1f + wave * 0.08f;
                chev.transform.localScale = Vector3.one * scaleMod;
            }
        }
    }

    private GameObject CreateChevronObject()
    {
        GameObject root = new GameObject("FloorChevron");
        root.transform.SetParent(this.transform);

        float halfWidth = chevronScale.x * 0.5f;
        float thickness = chevronScale.y;
        float armLength = chevronScale.z * 0.75f;

        // Left wing of the chevron
        GameObject leftWing = new GameObject("LeftWing");
        leftWing.transform.SetParent(root.transform);
        leftWing.transform.localPosition = new Vector3(-halfWidth * 0.45f, 0f, 0.04f);
        leftWing.transform.localRotation = Quaternion.Euler(0f, 32f, 0f);
        leftWing.transform.localScale = new Vector3(halfWidth * 0.45f, thickness, armLength);

        MeshFilter mf1 = leftWing.AddComponent<MeshFilter>();
        mf1.sharedMesh = chevronMesh;
        MeshRenderer mr1 = leftWing.AddComponent<MeshRenderer>();
        mr1.sharedMaterial = chevronMaterial;
        mr1.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;

        // Right wing of the chevron
        GameObject rightWing = new GameObject("RightWing");
        rightWing.transform.SetParent(root.transform);
        rightWing.transform.localPosition = new Vector3(halfWidth * 0.45f, 0f, 0.04f);
        rightWing.transform.localRotation = Quaternion.Euler(0f, -32f, 0f);
        rightWing.transform.localScale = new Vector3(halfWidth * 0.45f, thickness, armLength);

        MeshFilter mf2 = rightWing.AddComponent<MeshFilter>();
        mf2.sharedMesh = chevronMesh;
        MeshRenderer mr2 = rightWing.AddComponent<MeshRenderer>();
        mr2.sharedMaterial = chevronMaterial;
        mr2.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;

        return root;
    }

    private void ClearChevrons()
    {
        for (int i = 0; i < activeChevrons.Count; i++)
        {
            if (activeChevrons[i] != null)
            {
                Destroy(activeChevrons[i]);
            }
        }
        activeChevrons.Clear();
    }
}
