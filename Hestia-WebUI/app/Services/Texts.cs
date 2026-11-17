namespace Hestia.WebUI.Services;

using System.Text.Json;

/// <summary>
/// Texts the WebUI backend writes for a person (error details, chat notices, the OAuth result page) in the owner's
/// language. The source is English; the translation comes from the same catalog the browser loads
/// (Themis <c>/api/settings/i18n</c>, docs/LANGUAGES.md). Unknown text or unreachable settings → the English source.
/// </summary>
public class Texts
{
    private static readonly TimeSpan Fresh = TimeSpan.FromMinutes(5);
    private readonly IServiceScopeFactory _scopes;
    private readonly ILogger<Texts> _logger;
    private Dictionary<string, string> _messages = new();
    private DateTime _loadedAt = DateTime.MinValue;
    private int _loading;

    /// <summary>The app's instance (set when the container builds it, Program.cs), for static <see cref="Tr"/>.</summary>
    public static Texts? Instance { get; private set; }

    public Texts(IServiceScopeFactory scopes, ILogger<Texts> logger)
    {
        _scopes = scopes;
        _logger = logger;
        Instance = this;
    }

    /// <summary><c>Texts.Tr("Hub not reachable")</c> from anywhere (controllers, hubs, constants read at run time).</summary>
    public static string Tr(string english, params object?[] args) =>
        Instance?.T(english, args) ?? (args.Length == 0 ? english : string.Format(english, args));

    /// <summary><c>T("{0} not reachable", module)</c>: the owner's language, placeholders filled.</summary>
    public string T(string english, params object?[] args)
    {
        Refresh();
        var text = _messages.TryGetValue(english, out var tr) && !string.IsNullOrEmpty(tr) ? tr : english;
        return args.Length == 0 ? text : string.Format(text, args);
    }

    /// <summary>The catalog the browser just received (I18nController): no second fetch.</summary>
    public void Use(JsonElement payload)
    {
        if (payload.ValueKind != JsonValueKind.Object || !payload.TryGetProperty("messages", out var m)
            || m.ValueKind != JsonValueKind.Object) return;
        var map = new Dictionary<string, string>();
        foreach (var p in m.EnumerateObject())
            if (p.Value.ValueKind == JsonValueKind.String) map[p.Name] = p.Value.GetString() ?? "";
        _messages = map;
        _loadedAt = DateTime.UtcNow;
    }

    private void Refresh()
    {
        if (DateTime.UtcNow - _loadedAt < Fresh || Interlocked.Exchange(ref _loading, 1) == 1) return;
        _ = Task.Run(async () =>
        {
            try
            {
                using var scope = _scopes.CreateScope();
                var hub = scope.ServiceProvider.GetRequiredService<HubClient>();
                var (status, payload) = await hub.RouteRawAsync("themis", "/api/settings/i18n", HttpMethod.Get, timeoutSeconds: 3);
                if (status < 400) Use(payload);
                else _loadedAt = DateTime.UtcNow - Fresh + TimeSpan.FromSeconds(30);   // retry in 30 s
            }
            catch (Exception ex)
            {
                _logger.LogWarning("[🔄] event=webui_texts_unavailable error={Error} fallback=english", ex.Message);
                _loadedAt = DateTime.UtcNow - Fresh + TimeSpan.FromSeconds(30);
            }
            finally
            {
                Interlocked.Exchange(ref _loading, 0);
            }
        });
    }
}
