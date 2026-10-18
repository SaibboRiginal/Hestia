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

    private readonly ILogger<WebUISettings> _logger;
    private volatile bool _localWithoutToken = true;
    private volatile bool _loaded;

    public WebUISettings(ILogger<WebUISettings> logger) => _logger = logger;

    /// <summary>Home network / localhost may use the WebUI without the access token.</summary>
    public bool LocalWithoutToken => _localWithoutToken;

    public bool Loaded => _loaded;

    private static readonly object[] Definitions =
    {
        new Dictionary<string, object?>
        {
            ["key"] = LocalWithoutTokenKey,
            ["label"] = "Accesso senza token in rete locale",
            ["type"] = "bool",
            ["default"] = true,
            ["group"] = "Accesso",
            ["help"] = "Da casa (rete locale o localhost) la WebUI si apre senza token. Dal tunnel Cloudflare " +
                       "il token resta sempre obbligatorio. Spegni per chiedere il token ovunque.",
            ["apply"] = "live",
            ["scope"] = "system",
            ["oracle"] = "none",   // safety switch: the assistant can't even propose it
            ["advanced"] = false,
            ["order"] = 0,
        },
        // Client plugins (docs/work/2026-10-17-client-plugins §4.6): this client's own configuration of what
        // modules contribute. User scope → Themis layers profile → client "webui"; the frontend writes the
        // client layer. Oracle may only propose (dashboards are confirmed in the chat card).
        UserSetting("webui.plugins.hidden", "Plugin nascosti", "list", Array.Empty<string>(), 10,
            "Pagine e widget dei moduli nascosti in questa WebUI (es. scout.case, scout.*). Vuoto = tutto visibile."),
        UserSetting("webui.plugins.order", "Ordine delle pagine dei moduli", "list", Array.Empty<string>(), 11,
            "Ordine delle pagine dei moduli nella barra laterale."),
        UserSetting("webui.home.quick", "Azioni rapide in Home", "list", Array.Empty<string>(), 12,
            "Azioni rapide fissate (★) in Home, in ordine. Vuoto = quelle preferite e da fare oggi."),
        UserSetting("webui.dashboards", "Dashboard", "object", new Dictionary<string, object?> { ["dashboards"] = Array.Empty<object>() }, 13,
            "Dashboard della WebUI: titolo e widget dei moduli con posizione, misura e parametri.", oracle: "propose"),
        UserSetting("webui.plugins.prefs", "Preferenze dei plugin", "object", new Dictionary<string, object?>(), 14,
            "Preferenze che ogni plugin salva per questa WebUI."),
    };

    private static Dictionary<string, object?> UserSetting(string key, string label, string type, object? def,
        int order, string help, string oracle = "read") => new()
    {
        ["key"] = key, ["label"] = label, ["type"] = type, ["default"] = def, ["group"] = "Plugin e dashboard",
        ["help"] = help, ["apply"] = "live", ["scope"] = "user", ["oracle"] = oracle, ["advanced"] = true,
        ["order"] = order,
    };

    public Dictionary<string, object?> Values() => new() { [LocalWithoutTokenKey] = _localWithoutToken };

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
