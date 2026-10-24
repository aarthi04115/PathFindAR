using UnityEngine;

public class ArrowRotationSmoother : MonoBehaviour
{
    [Tooltip("How fast the arrow rotates toward its target rotation")]
    public float rotationSmoothSpeed = 8f;

    private Quaternion targetRotation;

    void Awake()
    {
        targetRotation = transform.rotation;
    }

    // Call this from other scripts when direction changes
    public void SetTargetRotation(Quaternion newRotation)
    {
        targetRotation = newRotation;
    }

    void LateUpdate()
    {
        transform.rotation = Quaternion.Slerp(
            transform.rotation,
            targetRotation,
            Time.deltaTime * rotationSmoothSpeed
        );
    }
}