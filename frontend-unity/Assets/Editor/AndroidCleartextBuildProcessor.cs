#if UNITY_EDITOR
using System.IO;
using System.Xml;
using UnityEditor.Android;
using UnityEngine;

/// <summary>
/// Automatically injects android:usesCleartextTraffic="true" into the unityLibrary AndroidManifest.xml
/// during Android player build so the app can reach local LAN FastAPI HTTP endpoints (e.g. http://192.168.1.6:8000).
/// </summary>
public class AndroidCleartextBuildProcessor : IPostGenerateGradleAndroidProject
{
    public int callbackOrder => 99;

    public void OnPostGenerateGradleAndroidProject(string path)
    {
        string manifestPath = Path.Combine(path, "src", "main", "AndroidManifest.xml");
        if (!File.Exists(manifestPath))
        {
            Debug.LogWarning("[AndroidCleartextBuildProcessor] AndroidManifest.xml not found at: " + manifestPath);
            return;
        }

        try
        {
            XmlDocument doc = new XmlDocument();
            doc.Load(manifestPath);

            XmlNode appNode = doc.SelectSingleNode("/manifest/application");
            if (appNode != null)
            {
                const string androidNs = "http://schemas.android.com/apk/res/android";
                XmlAttribute attr = appNode.Attributes["android:usesCleartextTraffic"] ?? appNode.Attributes["usesCleartextTraffic"];
                if (attr == null)
                {
                    attr = doc.CreateAttribute("android", "usesCleartextTraffic", androidNs);
                    attr.Value = "true";
                    appNode.Attributes.Append(attr);
                    doc.Save(manifestPath);
                    Debug.Log("[AndroidCleartextBuildProcessor] Successfully injected android:usesCleartextTraffic=\"true\" into " + manifestPath);
                }
                else if (attr.Value != "true")
                {
                    attr.Value = "true";
                    doc.Save(manifestPath);
                    Debug.Log("[AndroidCleartextBuildProcessor] Updated android:usesCleartextTraffic to \"true\" in " + manifestPath);
                }
            }
        }
        catch (System.Exception ex)
        {
            Debug.LogError("[AndroidCleartextBuildProcessor] Error injecting usesCleartextTraffic: " + ex.Message);
        }
    }
}
#endif
