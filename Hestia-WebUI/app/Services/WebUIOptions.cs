namespace Hestia.WebUI.Services;

using System.Security.Cryptography;

/// <summary>
/// Strongly-typed configuration for Hestia WebUI.
/// All tuneable values are in appsettings.json with env var overrides.
/// </summary>
public class WebUIOptions
{
    public const string Section = "WebUI";

    public int Port { get; set; } = 19015;
    public string SecretKey { get; set; } = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
    public double TokenLifetimeHours { get; set; } = 72;
    public int RateLimitPerMinute { get; set; } = 60;
    public int MaxUploadSizeMB { get; set; } = 50;
    public string CorsOrigin { get; set; } = "*";
    public string StaticDir { get; set; } = "wwwroot";
    public string OracleClientInstructions { get; set; } = "";
}

public class HestiaOptions
{
    public const string Section = "Hestia";

    public string HubApiUrl { get; set; } = "http://hestia_hub:19001/api";
    public string ServiceName { get; set; } = "webui";
    public string ServiceBaseUrl { get; set; } = "http://hestia_webui:19015";
    public string ServiceVersion { get; set; } = "1.0.0";
    public string ServiceType { get; set; } = "interface";
    public string ServiceTags { get; set; } = "interface,web";
    public string ServiceTopologyTags { get; set; } = "layer:client,domain:ui,status:new";
}
