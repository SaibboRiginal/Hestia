namespace Hestia.WebUI.Services;

using System.Text.Json;

/// <summary>
/// Client plugins seen by the WebUI (docs/work/2026-10-17-client-plugins §4): Hub's catalog for
/// <c>client=webui</c>, cached a few seconds. Also the guard of the plugin proxy: a plugin may call only its
/// own module, under the <c>api_prefix</c> its manifest declares. Hub unreachable → last catalog kept.
/// </summary>
public class PluginCatalog
{
    public const string Client = "webui";
    public const string Types = "page,widget,quick_action";
    private static readonly TimeSpan Ttl = TimeSpan.FromSeconds(15);

    private readonly IServiceScopeFactory _scopes;
    private readonly ILogger<PluginCatalog> _logger;
    private readonly SemaphoreSlim _lock = new(1, 1);
    private JsonElement? _catalog;
    private DateTime _fetchedAt = DateTime.MinValue;
    private Dictionary<string, string> _prefixes = new(StringComparer.OrdinalIgnoreCase);

    public PluginCatalog(IServiceScopeFactory scopes, ILogger<PluginCatalog> logger)
    {
        _scopes = scopes;
        _logger = logger;
    }

    /// <summary>Catalog JSON ({revision, ui_revision, modules, contributions}) or null if never reachable.</summary>
    public async Task<JsonElement?> GetAsync(bool fresh = false, CancellationToken ct = default)
    {
        if (!fresh && _catalog is not null && DateTime.UtcNow - _fetchedAt < Ttl) return _catalog;
        await _lock.WaitAsync(ct);
        try
        {
            if (!fresh && _catalog is not null && DateTime.UtcNow - _fetchedAt < Ttl) return _catalog;
            using var scope = _scopes.CreateScope();
            var hub = scope.ServiceProvider.GetRequiredService<HubClient>();
            var next = await hub.DiscoverCatalogAsync(Client, Types, ct);
            if (next is JsonElement cat && cat.ValueKind == JsonValueKind.Object)
            {
                _catalog = cat;
                _prefixes = ReadPrefixes(cat);
            }
            else if (_catalog is not null)
                _logger.LogInformation("[🔄] event=plugin_catalog_stale reason=hub_unreachable");
            _fetchedAt = DateTime.UtcNow;   // also after a failure: don't hammer Hub
            return _catalog;
        }
        finally { _lock.Release(); }
    }

    /// <summary>api_prefix of a module that ships a WebUI bundle, or null (unknown module / no UI).</summary>
    public async Task<string?> PrefixAsync(string module, CancellationToken ct = default)
    {
        await GetAsync(false, ct);
        if (!_prefixes.ContainsKey(module)) await GetAsync(true, ct);   // a module that just registered
        return _prefixes.TryGetValue(module, out var p) ? p : null;
    }

    /// <summary>True when <paramref name="path"/> (no traversal) is under the module's prefix.</summary>
    public static bool Allowed(string prefix, string path)
        => !string.IsNullOrEmpty(prefix) && path.StartsWith(prefix, StringComparison.Ordinal)
           && !path.Contains("..") && !path.Contains('\\') && !path.Contains("//");

    private static Dictionary<string, string> ReadPrefixes(JsonElement cat)
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (cat.TryGetProperty("contributions", out var contrib) && contrib.TryGetProperty(Client, out var webui)
            && webui.TryGetProperty("bundle", out var bundles) && bundles.ValueKind == JsonValueKind.Array)
            foreach (var b in bundles.EnumerateArray())
                if (b.TryGetProperty("module", out var m) && b.TryGetProperty("api_prefix", out var p))
                    map[m.GetString() ?? ""] = p.GetString() ?? "";
        return map;
    }
}
