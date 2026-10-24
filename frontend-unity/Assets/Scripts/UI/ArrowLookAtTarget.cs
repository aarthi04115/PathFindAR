using UnityEngine;

public class ArrowLookAtTarget : MonoBehaviour
{
    [Header("References")]
    public Transform cameraTransform;
    public Transform targetTransform;

    private ArrowRotationSmoother rotationSmoother;

    void Awake()
    {
        rotationSmoother = GetComponent<ArrowRotationSmoother>();

        // Auto-find Camera.main if unassigned
        if (cameraTransform == null && Camera.main != null)
        {
            cameraTransform = Camera.main.transform;
        }

        // Auto-find NavigationTarget if unassigned
        if (targetTransform == null)
        {
            GameObject targetObj = GameObject.Find("NavigationTarget");
            if (targetObj != null)
            {
                targetTransform = targetObj.transform;
            }
        }
    }

    void Update()
    {
        if (rotationSmoother == null)
        {
            rotationSmoother = GetComponent<ArrowRotationSmoother>();
        }

        if (cameraTransform == null && Camera.main != null)
        {
            cameraTransform = Camera.main.transform;
        }

        if (targetTransform == null)
        {
            GameObject targetObj = GameObject.Find("NavigationTarget");
            if (targetObj != null)
            {
                targetTransform = targetObj.transform;
            }
            if (targetTransform == null) return;
        }

        if (cameraTransform == null)
            return;

        // Direction from arrow to target (XZ only)
        Vector3 direction = targetTransform.position - transform.position;
        direction.y = 0f;

        if (direction.sqrMagnitude < 0.001f)
            return;

        Quaternion lookRotation = Quaternion.LookRotation(direction);

        // Send rotation to smoother
        if (rotationSmoother != null)
        {
            rotationSmoother.SetTargetRotation(lookRotation);
        }
    }
}