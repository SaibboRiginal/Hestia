namespace Hestia.WebUI.Services;

using System.Text.Json;

/// <summary>
/// WebUI's own central settings (Themis), the .NET counterpart of <c>hestia_common.settings_client</c>:
/// declared at start through Hub (<c>POST themis /api/settings/register</c>, answer = stored values),
/// re-asserted hourly (Themis keeps schemas in memory), pushed live by Themis on
/// <c>POST /api/settings/reload</c>. Themis unreachable → defaults (<c>[🔄]</c> log).
/// </summary>
public class WebUISettings
{
    public const string Owner = "webui";
    public const string LocalWithoutTokenKey = "webui.auth.local_without_token";
    public const string TransferRestorePointsKey = "webui.transfer.restore_points";

    private readonly ILogger<WebUISettings> _logger;
    private volatile bool _localWithoutToken = true;
    private volatile int _restorePoints = 5;
    private volatile bool _loaded;

    public WebUISettings(ILogger<WebUISettings> logger) => _logger = logger;

    /// <summary>Home network / localhost may use the WebUI without the access token.</summary>
    public bool LocalWithoutToken => _localWithoutToken;

    public bool Loaded => _loaded;

    /// <summary>Restore points kept by «Export and import» (newest first, older ones deleted).</summary>
    public int TransferRestorePoints => _restorePoints;

    private static readonly object[] Definitions =
    {
        new Dictionary<string, object?>
        {
            ["key"] = LocalWithoutTokenKey,
            ["label"] = "Access without token on the home network",
            ["type"] = "bool",
            ["default"] = true,
            ["group"] = "Access",
            ["help"] = "At home (local network or localhost) the WebUI opens without a token. Through the Cloudflare " +
                       "tunnel the token is always required. Turn off to ask for the token everywhere.",
            ["apply"] = "live",
            ["scope"] = "system",
            ["oracle"] = "none",   // safety switch: the assistant can't even propose it
            ["advanced"] = false,
            ["order"] = 0,
        },
        new Dictionary<string, object?>
        {
            ["key"] = TransferRestorePointsKey,
            ["label"] = "Restore points to keep",
            ["type"] = "int",
            ["default"] = 5,
            ["min"] = 1,
            ["max"] = 20,
            ["group"] = "Export and import",
            ["help"] = "Before every import a copy of what will change is saved. The most recent " +
                       "are kept, the others are deleted.",
            ["apply"] = "live",
            ["scope"] = "system",
            ["oracle"] = "propose",
            ["advanced"] = false,
            ["order"] = 1,
        },
        // Client plugins (docs/work/2026-10-17-client-plugins §4.6): this client's own configuration of what
        // modules contribute. User scope → Themis layers profile → client "webui"; the frontend writes the
        // client layer. Oracle may only propose (dashboards are confirmed in the chat card).
        UserSetting("webui.plugins.hidden", "Hidden plugins", "list", Array.Empty<string>(), 10,
            "Module pages and widgets hidden in this WebUI (e.g. scout.houses, scout.*). Empty = all visible."),
        UserSetting("webui.plugins.order", "Order of the module pages", "list", Array.Empty<string>(), 11,
            "Order of the module pages in the sidebar."),
        UserSetting("webui.home.quick", "Quick actions on Home", "list", Array.Empty<string>(), 12,
            "Quick actions pinned (★) on Home, in order. Empty = the favourite ones and those due today."),
        UserSetting("webui.dashboards", "Dashboard", "object", new Dictionary<string, object?> { ["dashboards"] = Array.Empty<object>() }, 13,
            "WebUI dashboards: title and module widgets with position, size and params.", oracle: "propose"),
        UserSetting("webui.plugins.prefs", "Plugin preferences", "object", new Dictionary<string, object?>(), 14,
            "Preferences each plugin saves for this WebUI."),
        // Sidebar arranged by the user (docs/work/2026-10-18-moduli-core-e-mcp-esterno §A5): pinned entries move
        // into «Pinned» and leave their own section (the list is computed, never stored twice).
        UserSetting("webui.sidebar.pinned", "Pinned sidebar entries", "list", Array.Empty<string>(), 15,
            "Sidebar entries pinned on top, in order (e.g. app.chat, scout.houses, dash.home)."),
        UserSetting("webui.sidebar.collapsed", "Collapsed sidebar sections", "list", Array.Empty<string>(), 16,
            "Closed sidebar sections (pinned, app, dashboards, modules, system)."),
    };

    private static Dictionary<string, object?> UserSetting(string key, string label, string type, object? def,
        int order, string help, string oracle = "read") => new()
    {
        ["key"] = key, ["label"] = label, ["type"] = type, ["default"] = def, ["group"] = "Plugins and dashboards",
        ["help"] = help, ["apply"] = "live", ["scope"] = "user", ["oracle"] = oracle, ["advanced"] = true,
        ["order"] = order,
    };

    public Dictionary<string, object?> Values() => new()
    {
        [LocalWithoutTokenKey] = _localWithoutToken, [TransferRestorePointsKey] = _restorePoints,
    };

    /// <summary>Declare definitions to Themis and apply the stored values it answers with.</summary>
    public async Task<bool> RegisterAsync(HubClient hub, CancellationToken ct = default)
    {
        var body = new Dictionary<string, object?>
        {
            ["owner"] = Owner, ["definitions"] = Definitions,
            ["presets"] = Array.Empty<object>(), ["effective"] = Values(),
        };
        var (status, payload) = await hub.RouteRawAsync("themis", "/api/settings/register", HttpMethod.Post,
            body: body, timeoutSeconds: 10, ct: ct);
        if (status >= 400 || payload.ValueKind != JsonValueKind.Object)
        {
            _logger.LogWarning("[🔄] event=settings_register_failed owner={Owner} status={Status} fallback=defaults",
                Owner, status);
            return false;
        }
        if (payload.TryGetProperty("values", out var values)) Apply(values);
        _loaded = true;
        _logger.LogInformation("event=settings_registered owner={Owner} definitions={N}", Owner, Definitions.Length);
        return true;
    }

    /// <summary>Apply stored values (missing key = back to default). Returns the changed keys.</summary>
    public List<string> Apply(JsonElement values)
    {
        var changed = new List<string>();
        var next = true;
        if (values.ValueKind == JsonValueKind.Object && values.TryGetProperty(LocalWithoutTokenKey, out var v)
            && v.ValueKind is JsonValueKind.True or JsonValueKind.False)
            next = v.GetBoolean();
        var points = 5;
        if (values.ValueKind == JsonValueKind.Object && values.TryGetProperty(TransferRestorePointsKey, out var rp)
            && rp.ValueKind == JsonValueKind.Number && rp.TryGetInt32(out var n))
            points = Math.Clamp(n, 1, 20);
        if (points != _restorePoints)
        {
            _restorePoints = points;
            changed.Add(TransferRestorePointsKey);
        }
        if (next != _localWithoutToken)
        {
            _localWithoutToken = next;
            changed.Add(LocalWithoutTokenKey);
            _logger.LogInformation("event=settings_applied owner={Owner} keys={Keys} local_without_token={V}",
                Owner, LocalWithoutTokenKey, next);
        }
        return changed;
    }
}

/// <summary>Registers <see cref="WebUISettings"/> on Themis: retry every 60 s until it answers, then hourly.</summary>
public class WebUISettingsRegistrar : BackgroundService
{
    private readonly WebUISettings _settings;
    private readonly IServiceScopeFactory _scopes;
    private readonly ILogger<WebUISettingsRegistrar> _logger;

    public WebUISettingsRegistrar(WebUISettings settings, IServiceScopeFactory scopes,
        ILogger<WebUISettingsRegistrar> logger)
    {
        _settings = settings;
        _scopes = scopes;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            var ok = false;
            try
            {
                using var scope = _scopes.CreateScope();
                ok = await _settings.RegisterAsync(scope.ServiceProvider.GetRequiredService<HubClient>(), stoppingToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning("[🔄] event=settings_register_failed owner={Owner} error={Error} fallback=defaults",
                    WebUISettings.Owner, ex.Message);
            }
            try { await Task.Delay(ok ? TimeSpan.FromHours(1) : TimeSpan.FromSeconds(60), stoppingToken); }
            catch (OperationCanceledException) { return; }
        }
    }
}
