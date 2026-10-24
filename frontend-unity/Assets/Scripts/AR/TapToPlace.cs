using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

public class TapToPlace : MonoBehaviour
{
    [Header("AR Managers")]
    public ARRaycastManager raycastManager;
    public ARAnchorManager anchorManager;

    [Header("Prefabs")]
    public GameObject markerPrefab;

    private ARAnchor spawnedAnchor;
    private GameObject spawnedMarker;

    private static List<ARRaycastHit> hits = new List<ARRaycastHit>();

    void Update()
    {
        if (Input.touchCount == 0)
            return;

        Touch touch = Input.GetTouch(0);

        if (touch.phase != TouchPhase.Began)
            return;

        // Raycast against detected horizontal planes
        if (raycastManager.Raycast(
            touch.position,
            hits,
            TrackableType.PlaneWithinPolygon))
        {
            Pose hitPose = hits[0].pose;

            // Remove old anchor if it exists
            if (spawnedAnchor != null)
            {
                Destroy(spawnedAnchor.gameObject);
                spawnedAnchor = null;
                spawnedMarker = null;
            }

            // Create a new GameObject at the hit position
            GameObject anchorObject = new GameObject("ARAnchor");

            anchorObject.transform.SetPositionAndRotation(
                hitPose.position,
                hitPose.rotation
            );

            // Add ARAnchor component
            spawnedAnchor = anchorObject.AddComponent<ARAnchor>();

            if (spawnedAnchor == null)
            {
                Debug.LogError("Failed to create anchor");
                Destroy(anchorObject);
                return;
            }

            // Spawn marker as a child of the anchor
            spawnedMarker = Instantiate(
                markerPrefab,
                spawnedAnchor.transform
            );

            // Slight height offset so it doesn't clip into the plane
            spawnedMarker.transform.localPosition =
                new Vector3(0f, 0.02f, 0f);

            spawnedMarker.transform.localRotation =
                Quaternion.identity;
        }
    }

    void LateUpdate()
    {
        if (spawnedAnchor == null)
            return;

        if (spawnedAnchor.trackingState == TrackingState.None)
        {
            Destroy(spawnedAnchor.gameObject);
            spawnedAnchor = null;
            spawnedMarker = null;
        }
    }
}