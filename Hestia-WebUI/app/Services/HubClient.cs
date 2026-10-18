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

    // ── Tools: Hestia's one MCP server (Hestia-MCP /mcp through Hub) ──────────
    // Every client lists and runs tools the same way (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2).
    private long _mcpId;

    /// <summary>MCP tools this client may see; Hestia details in <c>_meta.hestia</c>. Empty when unreachable.</summary>
    public async Task<List<JsonElement>> McpListToolsAsync(string client = "webui", CancellationToken ct = default)
    {
        try
        {
            var result = await McpRpcAsync(client, "tools/list",
                new Dictionary<string, object?> { ["_meta"] = new Dictionary<string, object?> { ["hestia"] = new { client } } },
                15, ct);
            if (result.TryGetProperty("tools", out var tools) && tools.ValueKind == JsonValueKind.Array)
                return tools.EnumerateArray().ToList();
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException or InvalidOperationException)
        {
            _logger.LogWarning(ex, "event=mcp_list_tools_failed client={Client}", client);
        }
        return [];
    }

    /// <summary>Runs one tool. Ok=false carries the module's error payload (or a <c>{detail}</c>).</summary>
    public async Task<(bool Ok, JsonElement Payload)> McpCallToolAsync(
        string client, string name, Dictionary<string, object> args, string? sessionId = null,
        double timeoutSeconds = 30, CancellationToken ct = default)
    {
        var hestia = new Dictionary<string, object?> { ["timeout_seconds"] = timeoutSeconds };
        if (!string.IsNullOrEmpty(sessionId)) hestia["session_id"] = sessionId;
        var result = await McpRpcAsync(client, "tools/call", new Dictionary<string, object?>
        {
            ["name"] = name, ["arguments"] = args,
            ["_meta"] = new Dictionary<string, object?> { ["hestia"] = hestia },
        }, timeoutSeconds + 2, ct);
        if (result.ValueKind != JsonValueKind.Object)
            return (false, JsonSerializer.SerializeToElement(new { detail = "empty answer from mcp" }));
        var isError = result.TryGetProperty("isError", out var e) && e.ValueKind == JsonValueKind.True;
        var payload = result.TryGetProperty("structuredContent", out var sc) ? sc : result;
        var wrapped = result.TryGetProperty("_meta", out var meta) && meta.TryGetProperty("hestia", out var h)
                      && h.TryGetProperty("wrapped", out var w) && w.ValueKind == JsonValueKind.True;
        if (wrapped && payload.TryGetProperty("result", out var inner)) payload = inner;
        return (!isError, payload);
    }

    /// <summary>MCP tool → the command shape the WebUI pages use (arguments_schema = JSON schema).</summary>
    public static Dictionary<string, object?> ToolAsCommand(JsonElement tool)
    {
        string Str(JsonElement el, string key, string def = "") =>
            el.ValueKind == JsonValueKind.Object && el.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
                ? v.GetString() ?? def : def;
        var meta = tool.TryGetProperty("_meta", out var m) && m.TryGetProperty("hestia", out var hm) ? hm : default;
        var name = Str(tool, "name");
        return new Dictionary<string, object?>
        {
            ["command"] = name,
            ["title"] = Str(tool, "title", name),
            ["description"] = Str(tool, "description"),
            ["service"] = Str(meta, "service"),
            ["method"] = Str(meta, "method", "GET"),
            ["path"] = Str(meta, "path"),
            ["response_mode"] = Str(meta, "response_mode", "oracle_natural"),
            ["response_prompt"] = Str(meta, "response_prompt"),
            ["clients"] = meta.ValueKind == JsonValueKind.Object && meta.TryGetProperty("clients", out var c) ? (object)c : null,
            ["arguments_schema"] = tool.TryGetProperty("inputSchema", out var schema) ? (object)schema : null,
        };
    }

    private async Task<JsonElement> McpRpcAsync(string client, string method, object parameters, double timeoutSeconds,
        CancellationToken ct)
    {
        var envelope = new Dictionary<string, object?>
        {
            ["method"] = "POST",
            ["timeout_seconds"] = timeoutSeconds,
            ["headers"] = new Dictionary<string, string> { ["X-Hestia-Client"] = client },
            ["body"] = new Dictionary<string, object?>
            {
                ["jsonrpc"] = "2.0", ["id"] = Interlocked.Increment(ref _mcpId), ["method"] = method, ["params"] = parameters,
            },
        };
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds + 5));
        var resp = await _http.PostAsync($"{_hubUrl}/route/mcp/mcp",
            new StringContent(JsonSerializer.Serialize(envelope), Encoding.UTF8, "application/json"), cts.Token);
        resp.EnsureSuccessStatusCode();
        var routed = await resp.Content.ReadFromJsonAsync<JsonElement>(cancellationToken: ct);
        if (routed.TryGetProperty("status_code", out var status) && status.ValueKind == JsonValueKind.Number
            && status.GetInt32() >= 400)
            throw new InvalidOperationException($"mcp returned {status.GetInt32()}");
        var payload = routed.TryGetProperty("payload", out var p) ? p : routed;
        if (payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty("error", out var err))
            throw new InvalidOperationException(err.TryGetProperty("message", out var msg) ? msg.GetString() : "mcp error");
        return payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty("result", out var result)
            ? result : default;
    }

    /// <summary>One catalog of module contributions for a client (tools, commands, pages, widgets,
    /// quick actions, bundles) — Hub <c>/api/discovery/catalog</c>.</summary>
    public async Task<JsonElement?> DiscoverCatalogAsync(
        string client, string types, CancellationToken ct = default)
    {
        try
        {
            var resp = await _http.GetAsync(
                $"{_hubUrl}/discovery/catalog?client={Uri.EscapeDataString(client)}&type={Uri.EscapeDataString(types)}", ct);
            resp.EnsureSuccessStatusCode();
            return await resp.Content.ReadFromJsonAsync<JsonElement>(cancellationToken: ct);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            _logger.LogWarning("[🔄] event=hub_discovery_catalog_failed error={Error}", ex.Message);
            return null;
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

    /// <summary>Any method (PATCH, DELETE with query, ...) through Hub routing.</summary>
    public Task<JsonElement> RouteAsyncPublic(
        string service, string path, HttpMethod method, object? body = null,
        Dictionary<string, string>? query = null, double timeoutSeconds = 20, CancellationToken ct = default)
        => RouteAsync(service, path, method, query: query, body: body, timeoutSeconds: timeoutSeconds, ct: ct);

    /// <summary>
    /// Routing call that never throws on a target 4xx/5xx: returns (status, payload) so a
    /// caller can forward the module's answer (e.g. Hermes 409 "already_handled").
    /// Status 502 = Hub unreachable.
    /// </summary>
    public async Task<(int Status, JsonElement Payload)> RouteRawAsync(
        string service, string path, HttpMethod method, object? body = null,
        Dictionary<string, string>? query = null, double timeoutSeconds = 20, CancellationToken ct = default)
    {
        var envelope = new Dictionary<string, object?> { ["method"] = method.Method, ["timeout_seconds"] = timeoutSeconds };
        if (query?.Count > 0) envelope["query"] = query;
        if (body is not null) envelope["body"] = body;
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds + 5));
            var resp = await _http.PostAsync($"{_hubUrl}/route/{service}/{path.TrimStart('/')}",
                new StringContent(JsonSerializer.Serialize(envelope), Encoding.UTF8, "application/json"), cts.Token);
            var result = await resp.Content.ReadFromJsonAsync<JsonElement>(cancellationToken: ct);
            if (!resp.IsSuccessStatusCode)
                return ((int)resp.StatusCode, result);
            var status = result.TryGetProperty("status_code", out var sc) && sc.ValueKind == JsonValueKind.Number
                ? sc.GetInt32() : 200;
            return (status, result.TryGetProperty("payload", out var payload) ? payload : result);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            _logger.LogWarning(ex, "event=hub_route_raw_failed service={Svc} path={Path}", service, path);
            return (502, JsonSerializer.SerializeToElement(new { detail = ex.Message }));
        }
    }

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
