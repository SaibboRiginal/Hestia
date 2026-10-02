namespace Hestia.WebUI.Services;

/// <summary>
/// Tracks the public-facing URL of the WebUI (e.g. Cloudflare tunnel domain).
/// Auto-detected from Host header on external requests, or set manually via API.
/// Used by Telegram to generate clickable links.
/// </summary>
public class PublicUrlService
{
    private string? _publicUrl;
    private bool _manual;            // set explicitly (tunnel script / admin) → never overridden by Host
    private readonly object _lock = new();
    private readonly ILogger<PublicUrlService> _logger;

    // Known local/private hostnames that are NOT the public URL
    private static readonly HashSet<string> LocalHosts = new(StringComparer.OrdinalIgnoreCase)
    {
        "localhost", "127.0.0.1", "::1", "0.0.0.0",
        "hestia_webui", "hestia_webui:19015",
    };

    public PublicUrlService(ILogger<PublicUrlService> logger)
    {
        _logger = logger;
    }

    // Only hosts under these suffixes may be auto-detected (Host header is client-controlled:
    // an arbitrary value would let anyone redirect the login link — and the token — elsewhere).
    private static readonly string[] AllowedSuffixes =
        (Environment.GetEnvironmentVariable("WEBUI_PUBLIC_HOST_SUFFIXES") ?? ".trycloudflare.com")
        .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    /// <summary>Try to auto-detect from a Host header value (Cloudflare traffic only, never over a manual URL).</summary>
    public void TryDetectFromHost(string host, string scheme = "https", bool viaCloudflare = false)
    {
        if (string.IsNullOrWhiteSpace(host) || !viaCloudflare) return;
        lock (_lock) { if (_manual) return; }

        // Strip port
        var cleanHost = host.Split(':')[0];

        // Skip known local hosts
        if (LocalHosts.Contains(cleanHost)) return;
        if (cleanHost.EndsWith(".local") || cleanHost.EndsWith(".internal")) return;

        // Must look like a real domain (contains a dot and TLD)
        if (!cleanHost.Contains('.') || cleanHost.Split('.').Last().Length < 2) return;

        if (!AllowedSuffixes.Any(sfx => cleanHost.EndsWith(sfx, StringComparison.OrdinalIgnoreCase))) return;

        SetPublicUrl($"https://{cleanHost}", manual: false);
    }

    /// <summary>Manually set the public URL.</summary>
    public void SetPublicUrl(string url, bool manual = true)
    {
        url = url.TrimEnd('/');
        lock (_lock)
        {
            if (manual) _manual = true;
            if (_publicUrl != url)
            {
                _publicUrl = url;
                _logger.LogInformation("event=public_url_set url={Url}", url);
            }
        }
    }

    /// <summary>Get the current public URL, or null if not detected.</summary>
    public string? GetPublicUrl()
    {
        lock (_lock) return _publicUrl;
    }
}
