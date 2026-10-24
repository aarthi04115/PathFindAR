using UnityEngine;
using UnityEngine.XR.ARFoundation;
using Unity.XR.CoreUtils;

public class ARWorldOriginCache : MonoBehaviour
{
    [Header("References")]
    public XROrigin xrOrigin;
    public ARSession arSession;

    [Header("Cached Initial World Origin")]
    public Vector3 initialPosition;
    public Quaternion initialRotation;

    private bool originCached = false;

    // =========================
    // Drift Correction Settings
    // =========================
    [Header("Drift Correction")]
    [Tooltip("Meters before positional correction starts")]
    public float positionDriftThreshold = 0.05f;   // 5 cm

    [Tooltip("Degrees before rotational correction starts")]
    public float rotationDriftThreshold = 2f;      // 2 degrees

    [Tooltip("How fast correction happens (smooth)")]
    public float correctionSpeed = 0.5f;

    // Target (backend-aligned) pose
    private Vector3 targetPosition;
    private Quaternion targetRotation;

    // =========================
    // 1.5.1 — Cache AR World Origin
    // =========================
    void Update()
    {
        if (originCached)
            return;

        // Only cache once AR tracking is stable (REAL DEVICE)
        if (ARSession.state == ARSessionState.SessionTracking)
        {
            CacheWorldOrigin();
        }
    }

    void CacheWorldOrigin()
    {
        initialPosition = xrOrigin.transform.position;
        initialRotation = xrOrigin.transform.rotation;

        // Initialize drift targets
        targetPosition = initialPosition;
        targetRotation = initialRotation;

        originCached = true;

        Debug.Log("AR World Origin cached.");
    }

    // =========================
    // 1.5.2 & 1.5.3 — Apply Backend World Pose
    // =========================
    public void ApplyBackendWorldPose(Vector3 backendPosition, Quaternion backendRotation)
    {
        if (!originCached)
        {
            Debug.LogWarning("World origin not cached yet. Cannot apply backend pose.");
            return;
        }

        // Calculate offsets
        Vector3 positionOffset = backendPosition - initialPosition;
        Quaternion rotationOffset = backendRotation * Quaternion.Inverse(initialRotation);

        // Apply to XR Origin
        xrOrigin.transform.position += positionOffset;
        xrOrigin.transform.rotation = rotationOffset * xrOrigin.transform.rotation;

        // Update drift targets
        targetPosition = xrOrigin.transform.position;
        targetRotation = xrOrigin.transform.rotation;

        Debug.Log("Backend world pose applied.");
    }

    // =========================
    // 1.5.4 — Drift Correction
    // =========================
    void LateUpdate()
    {
        if (!originCached)
            return;

        // Position drift
        float positionError = Vector3.Distance(
            xrOrigin.transform.position,
            targetPosition
        );

        // Rotation drift
        float rotationError = Quaternion.Angle(
            xrOrigin.transform.rotation,
            targetRotation
        );

        // Apply smooth correction ONLY if beyond thresholds
        if (positionError > positionDriftThreshold)
        {
            xrOrigin.transform.position = Vector3.Lerp(
                xrOrigin.transform.position,
                targetPosition,
                Time.deltaTime * correctionSpeed
            );
        }

        if (rotationError > rotationDriftThreshold)
        {
            xrOrigin.transform.rotation = Quaternion.Slerp(
                xrOrigin.transform.rotation,
                targetRotation,
                Time.deltaTime * correctionSpeed
            );
        }
    }

    // =========================
    // EDITOR TESTING (SAFE)
    // =========================
#if UNITY_EDITOR
    [ContextMenu("TEST Apply Backend Offset")]
    void TestApplyBackendOffset()
    {
        if (!originCached)
        {
            // Editor does not reach SessionTracking naturally
            CacheWorldOrigin();
        }

        Vector3 fakeBackendPosition = initialPosition + new Vector3(0.5f, 0f, 0.5f);
        Quaternion fakeBackendRotation = Quaternion.Euler(0f, 30f, 0f);

        ApplyBackendWorldPose(fakeBackendPosition, fakeBackendRotation);
    }
#endif
}