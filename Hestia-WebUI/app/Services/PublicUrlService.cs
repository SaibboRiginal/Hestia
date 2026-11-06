namespace Hestia.WebUI.Services;

using System.Text.Json;

/// <summary>
/// Tracks the public-facing URL of the WebUI (e.g. Cloudflare tunnel domain).
/// Auto-detected from Host header on external requests, or set manually via API.
/// Used by Telegram to generate clickable links.
/// </summary>
public class PublicUrlService
{
    private string? _publicUrl;
    private bool _manual;            // set explicitly (tunnel script / admin) → never overridden by Host
    private bool _fromTunnel;        // read from the «Da fuori casa» tunnel container (Hephaestus starts it)
    private DateTime _tunnelChecked = DateTime.MinValue;
    private int _tunnelChecking;

    // «Da fuori casa» (docs/work/2026-10-30-setup-un-click): cloudflared's metrics give the quick tunnel's address.
    // Infrastructure address on hestia_net like Ollama's; the container exists only while the user wants it.
    private const string TunnelQuickUrl = "http://hestia_tunnel:20241/quicktunnel";
    private static readonly HttpClient TunnelHttp = new() { Timeout = TimeSpan.FromSeconds(2) };
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

    /// <summary>
    /// True when <paramref name="host"/> is a public (tunnel) hostname: under the allowed suffixes or the
    /// host of the current public URL. Used by <see cref="LocalAccess"/> to require the token.
    /// </summary>
    public bool IsPublicHost(string host)
    {
        var cleanHost = (host ?? "").Split(':')[0].Trim().TrimEnd('.');
        if (cleanHost.Length == 0) return false;
        if (AllowedSuffixes.Any(sfx => cleanHost.EndsWith(sfx, StringComparison.OrdinalIgnoreCase))) return true;
        var url = GetPublicUrl();
        return url is not null && Uri.TryCreate(url, UriKind.Absolute, out var u)
               && string.Equals(u.Host, cleanHost, StringComparison.OrdinalIgnoreCase);
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
        RefreshFromTunnel();
        lock (_lock) return _publicUrl;
    }

    /// <summary>
    /// At most once a minute, in the background (never blocks a request): the tunnel's current address, or none
    /// when the tunnel is off (an address that came from it is then forgotten). A manual URL always wins.
    /// </summary>
    private void RefreshFromTunnel()
    {
        lock (_lock)
        {
            if (_manual || DateTime.UtcNow - _tunnelChecked < TimeSpan.FromSeconds(60)) return;
            _tunnelChecked = DateTime.UtcNow;
        }
        if (Interlocked.Exchange(ref _tunnelChecking, 1) == 1) return;
        _ = Task.Run(async () =>
        {
            try
            {
                using var doc = JsonDocument.Parse(await TunnelHttp.GetStringAsync(TunnelQuickUrl));
                var host = doc.RootElement.TryGetProperty("hostname", out var h) ? h.GetString() : null;
                if (string.IsNullOrWhiteSpace(host)) return;
                lock (_lock)
                {
                    if (_manual) return;
                    _fromTunnel = true;
                }
                SetPublicUrl($"https://{host}", manual: false);
            }
            catch (Exception)
            {
                lock (_lock)
                {
                    if (_fromTunnel)
                    {
                        _logger.LogInformation("event=public_url_tunnel_gone");
                        _publicUrl = null;
                        _fromTunnel = false;
                    }
                }
            }
            finally
            {
                Interlocked.Exchange(ref _tunnelChecking, 0);
            }
        });
    }
}
