using UnityEngine;

public class PulseEffect : MonoBehaviour
{
    public float pulseSpeed = 2f;   // speed of pulsing
    public float pulseAmount = 0.05f; // how much it grows/shrinks

    private Vector3 startScale;

    void Start()
    {
        startScale = transform.localScale;
    }

    void Update()
    {
        float scaleOffset = Mathf.Sin(Time.time * pulseSpeed) * pulseAmount;
        transform.localScale = startScale + Vector3.one * scaleOffset;
    }
}