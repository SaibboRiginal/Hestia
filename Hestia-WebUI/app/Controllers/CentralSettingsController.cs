namespace Hestia.WebUI.Controllers;

using System.Net;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Impostazioni → Sistema: central settings owned by Themis (schema, values, state, presets,
/// history/undo, pending proposals). Thin proxy: browser → WebUI → Hub → Themis /api/settings*.
/// Every change made here is the user's ("webui"); the assistant can only propose via Themis.
/// </summary>
[ApiController]
[Route("api/webui/central-settings")]
public class CentralSettingsController : ControllerBase
{
    private const string Svc = "themis";
    private const string Base = "/api/settings";
    private const string Client = "webui";

    private readonly HubClient _hub;
    private readonly SessionManager _sessions;
    private readonly ILogger<CentralSettingsController> _logger;

    public CentralSettingsController(HubClient hub, SessionManager sessions, ILogger<CentralSettingsController> logger)
    {
        _hub = hub;
        _sessions = sessions;
        _logger = logger;
    }

    [HttpGet("revision")]
    public Task<IActionResult> Revision() => Wrap(() => _hub.RouteGetAsync(Svc, $"{Base}/revision", null, 5));

    /// <summary>Modules with settings + live health (Hub) + pending proposals: the panel's dashboard.</summary>
    [HttpGet("modules")]
    public Task<IActionResult> Modules() => Wrap(() => _hub.RouteGetAsync(Svc, $"{Base}/modules", null, 20));

    /// <summary>Definitions with value, source and state; user-scope values resolved for this client.</summary>
    [HttpGet("items")]
    public Task<IActionResult> Items([FromQuery] string? module = null, [FromQuery] string? q = null)
        => Wrap(() => _hub.RouteGetAsync(Svc, Base,
            Query(("module", module), ("q", q), ("client", Client), ("session", _sessions.GetSession())), 20));

    [HttpGet("key/{key}/options")]
    public Task<IActionResult> Options(string key)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{KeyPath(key)}/options",
            Query(("client", Client), ("session", _sessions.GetSession())), 15));

    /// <summary>Set a value: body {value, scope?, scope_id?}. Actor is always this client.</summary>
    [HttpPut("key/{key}")]
    public Task<IActionResult> Set(string key, [FromBody] JsonElement body)
    {
        var dict = ToDict(body);
        dict["actor"] = Client;
        dict.Remove("reason");
        ScopeTarget(dict);
        _logger.LogInformation("event=webui_central_setting_set key={Key}", key);
        return Wrap(() => _hub.RoutePutAsync(Svc, KeyPath(key), dict));
    }

    [HttpDelete("key/{key}")]
    public Task<IActionResult> Reset(string key, [FromQuery] string? scope = null)
        => Wrap(() => _hub.RouteAsyncPublic(Svc, KeyPath(key), HttpMethod.Delete,
            query: Query(("scope", scope), ("scope_id", ScopeId(scope)), ("actor", Client))));

    [HttpGet("key/{key}/history")]
    public Task<IActionResult> History(string key, [FromQuery] string? scope = null, [FromQuery] string? scope_id = null)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{KeyPath(key)}/history",
            Query(("scope", scope), ("scope_id", scope_id), ("limit", "10"))));

    [HttpPost("key/{key}/undo")]
    public Task<IActionResult> Undo(string key, [FromBody] JsonElement? body = null)
    {
        var dict = body is JsonElement b ? ToDict(b) : new Dictionary<string, object?>();
        dict["actor"] = Client;
        return Wrap(() => _hub.RoutePostAsync(Svc, $"{KeyPath(key)}/undo", dict));
    }

    [HttpPost("presets/{module}/{presetId}/apply")]
    public Task<IActionResult> ApplyPreset(string module, string presetId)
        => Wrap(() => _hub.RoutePostAsync(Svc,
            $"{Base}/presets/{Uri.EscapeDataString(module)}/{Uri.EscapeDataString(presetId)}/apply",
            new Dictionary<string, object?> { ["actor"] = Client }, 30));

    [HttpGet("proposals")]
    public Task<IActionResult> Proposals() => Wrap(() => _hub.RouteGetAsync(Svc, $"{Base}/proposals"));

    /// <summary>The user answers an assistant proposal from this client (first answer wins: 409 otherwise).</summary>
    [HttpPost("proposals/{id}/{verb:regex(^(approve|reject)$)}")]
    public Task<IActionResult> Decide(string id, string verb)
        => Wrap(() => _hub.RoutePostAsync(Svc, $"{Base}/proposals/{Uri.EscapeDataString(id)}/{verb}",
            new Dictionary<string, object?> { ["by"] = Client }));

    // ── helpers ────────────────────────────────────────────────────────

    /// <summary>User settings layers this client may write: profile (defaults), client "webui",
    /// session = the current WebUI conversation (chat quick menu). The id is decided here.</summary>
    private string? ScopeId(string? scope) => scope switch
    {
        "session" => _sessions.GetSession(),
        "client" => Client,
        _ => null,
    };

    private void ScopeTarget(Dictionary<string, object?> dict)
    {
        var scope = dict.TryGetValue("scope", out var s) ? s?.ToString() : null;
        if (string.IsNullOrWhiteSpace(scope)) { dict.Remove("scope"); dict.Remove("scope_id"); return; }
        var id = ScopeId(scope);
        if (id is null) dict.Remove("scope_id"); else dict["scope_id"] = id;
    }

    private static string KeyPath(string key) => $"{Base}/key/{Uri.EscapeDataString(key)}";

    private static Dictionary<string, string> Query(params (string Key, string? Value)[] pairs)
    {
        var q = new Dictionary<string, string>();
        foreach (var (k, v) in pairs)
            if (!string.IsNullOrWhiteSpace(v)) q[k] = v;
        return q;
    }

    private static Dictionary<string, object?> ToDict(JsonElement body)
        => body.ValueKind == JsonValueKind.Object
            ? JsonSerializer.Deserialize<Dictionary<string, object?>>(body.GetRawText()) ?? new()
            : new();

    /// <summary>Themis answers errors as {detail: "…"} (Italian, user-facing): pass that text through.</summary>
    private static string Detail(string message)
    {
        var start = message.IndexOf('{');
        if (start < 0) return message;
        try
        {
            using var doc = JsonDocument.Parse(message[start..]);
            if (doc.RootElement.TryGetProperty("detail", out var d) && d.ValueKind == JsonValueKind.String)
                return d.GetString() ?? message;
        }
        catch (JsonException) { /* truncated payload: keep the raw message */ }
        return message;
    }

    private async Task<IActionResult> Wrap(Func<Task<JsonElement>> call)
    {
        try
        {
            return Ok(await call());
        }
        catch (HttpRequestException ex)
        {
            _logger.LogWarning("event=webui_central_settings_call_failed error={Error}", ex.Message);
            var code = ex.StatusCode is HttpStatusCode sc ? (int)sc : 502;
            return StatusCode(code >= 400 ? code : 502, new { detail = Detail(ex.Message) });
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=webui_central_settings_call_error");
            return StatusCode(502, new { detail = "Impostazioni non raggiungibili (Themis)" });
        }
    }
}
