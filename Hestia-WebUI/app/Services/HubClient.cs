namespace Hestia.WebUI.Services;

using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;

/// <summary>
/// Hub API client — all inter-service calls go through Hub routing.
/// Follows Hestia architecture rule: every service knows exactly one address: HUB_API_URL.
/// </summary>
public class HubClient
{
    private readonly HttpClient _http;
    private readonly string _hubUrl;
    private readonly ILogger<HubClient> _logger;

    public HubClient(HttpClient http, IOptions<HestiaOptions> options, ILogger<HubClient> logger)
    {
        _http = http;
        _hubUrl = options.Value.HubApiUrl.TrimEnd('/');
        _logger = logger;
    }

    // ── Registry / Discovery ───────────────────────────────────────────

    /// <summary>Get all registered services and their status.</summary>
    public async Task<JsonElement> GetRegistryAsync(CancellationToken ct = default)
    {
        var resp = await _http.GetAsync($"{_hubUrl}/status", ct);
        resp.EnsureSuccessStatusCode();
        return await resp.Content.ReadFromJsonAsync<JsonElement>(cancellationToken: ct);
    }

    /// <summary>Discover commands available to a given client.</summary>
    public async Task<List<JsonElement>> DiscoverCommandsAsync(
        string client = "ui", CancellationToken ct = default)
    {
        try
        {
            var resp = await _http.GetAsync(
                $"{_hubUrl}/discovery/commands?client={client}", ct);
            resp.EnsureSuccessStatusCode();
            var json = await resp.Content.ReadFromJsonAsync<JsonElement>(cancellationToken: ct);
            if (json.TryGetProperty("commands", out var commands))
                return commands.EnumerateArray().ToList();
            return [];
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=hub_discovery_commands_failed");
            return [];
        }
    }

    /// <summary>Get a single service from the registry.</summary>
    public async Task<JsonElement?> GetServiceAsync(
        string serviceName, CancellationToken ct = default)
    {
        var registry = await GetRegistryAsync(ct);
        if (registry.TryGetProperty("services", out var services))
        {
            foreach (var svc in services.EnumerateArray())
            {
                if (svc.TryGetProperty("name", out var name)
                    && name.GetString() == serviceName)
                    return svc;
            }
        }
        return null;
    }

    // ── Routing ────────────────────────────────────────────────────────

    public Task<JsonElement> RouteGetAsync(
        string service, string path,
        Dictionary<string, string>? query = null,
        double timeoutSeconds = 15,
        CancellationToken ct = default)
        => RouteAsync(service, path, HttpMethod.Get, query: query,
            timeoutSeconds: timeoutSeconds, ct: ct);

    public Task<JsonElement> RoutePostAsync(
        string service, string path,
        object? body = null,
        double timeoutSeconds = 20,
        CancellationToken ct = default)
        => RouteAsync(service, path, HttpMethod.Post, body: body,
            timeoutSeconds: timeoutSeconds, ct: ct);

    public Task<JsonElement> RoutePutAsync(
        string service, string path,
        object? body = null,
        double timeoutSeconds = 20,
        CancellationToken ct = default)
        => RouteAsync(service, path, HttpMethod.Put, body: body,
            timeoutSeconds: timeoutSeconds, ct: ct);

    public Task<JsonElement> RouteDeleteAsync(
        string service, string path,
        double timeoutSeconds = 10,
        CancellationToken ct = default)
        => RouteAsync(service, path, HttpMethod.Delete,
            timeoutSeconds: timeoutSeconds, ct: ct);

    /// <summary>Core routing call through Hub's /api/route/{service}/{path}.</summary>
    private async Task<JsonElement> RouteAsync(
        string service, string path, HttpMethod method,
        Dictionary<string, string>? query = null,
        object? body = null,
        double timeoutSeconds = 15,
        CancellationToken ct = default)
    {
        var cleanPath = path.TrimStart('/');
        var url = $"{_hubUrl}/route/{service}/{cleanPath}";

        var envelope = new Dictionary<string, object?>
        {
            ["method"] = method.Method,
            ["timeout_seconds"] = timeoutSeconds
        };
        if (query?.Count > 0) envelope["query"] = query;
        if (body is not null) envelope["body"] = body;

        var content = new StringContent(
            JsonSerializer.Serialize(envelope),
            Encoding.UTF8,
            "application/json");

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds + 5));

        var resp = await _http.PostAsync(url, content, cts.Token);
        resp.EnsureSuccessStatusCode();

        var result = await resp.Content.ReadFromJsonAsync<JsonElement>(
            cancellationToken: ct);

        // Unwrap unicast response: {status_code, service, target, payload}.
        // A target-side 4xx/5xx arrives as HTTP 200 from Hub: surface it as an error.
        if (result.TryGetProperty("status_code", out var sc) && sc.ValueKind == JsonValueKind.Number
            && sc.GetInt32() >= 400)
        {
            var detail = result.TryGetProperty("payload", out var errPayload) ? errPayload.ToString() : "";
            _logger.LogWarning("event=hub_route_target_error service={Svc} path={Path} status={Status} detail={Detail}",
                service, cleanPath, sc.GetInt32(), detail.Length > 300 ? detail[..300] : detail);
            throw new HttpRequestException(
                $"{service}/{cleanPath} returned {sc.GetInt32()}: {(detail.Length > 300 ? detail[..300] : detail)}",
                null, (System.Net.HttpStatusCode)sc.GetInt32());
        }
        if (result.TryGetProperty("payload", out var payload))
            return payload;

        return result;
    }
}
