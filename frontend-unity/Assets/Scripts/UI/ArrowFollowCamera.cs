using UnityEngine;

public class ArrowFollowCamera : MonoBehaviour
{
    public Transform cameraTransform;
    public float distanceFromCamera = 0.6f;

    void LateUpdate()
    {
        if (cameraTransform == null)
            return;

        Vector3 forward = cameraTransform.forward;
        forward.y = 0f;
        forward.Normalize();

        transform.position = cameraTransform.position + forward * distanceFromCamera;
    }
}