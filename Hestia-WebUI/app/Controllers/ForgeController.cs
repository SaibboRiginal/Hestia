namespace Hestia.WebUI.Controllers;

using System.Net;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// "Sviluppo" page: Forge tasks (transcript, changes, dossier, tests, logs, actions) and the
/// read-only repository browser. Thin proxy: browser → WebUI → Hub → Hephaestus
/// /api/hephaestus/forge/* and /api/hephaestus/repo/*. Token-protected by the middleware.
/// </summary>
[ApiController]
[Route("api/webui/forge")]
public class ForgeController : ControllerBase
{
    private const string Svc = "hephaestus";
    private const string Forge = "/api/hephaestus/forge";
    private const string Repo = "/api/hephaestus/repo";

    private readonly HubClient _hub;
    private readonly ILogger<ForgeController> _logger;

    public ForgeController(HubClient hub, ILogger<ForgeController> logger)
    {
        _hub = hub;
        _logger = logger;
    }

    // ── Forge ──────────────────────────────────────────────────────────

    [HttpGet("status")]
    public Task<IActionResult> Status() => Wrap(() => _hub.RouteGetAsync(Svc, $"{Forge}/status", null, 20));

    [HttpGet("settings")]
    public Task<IActionResult> Settings() => Wrap(() => _hub.RouteGetAsync(Svc, $"{Forge}/settings"));

    [HttpGet("tasks")]
    public Task<IActionResult> Tasks([FromQuery] string? state = null, [FromQuery] int limit = 100)
    {
        var q = new Dictionary<string, string> { ["limit"] = Math.Clamp(limit, 1, 200).ToString() };
        if (!string.IsNullOrWhiteSpace(state)) q["state"] = state;
        return Wrap(() => _hub.RouteGetAsync(Svc, $"{Forge}/tasks", q));
    }

    /// <summary>New development task ({request, services?, engine?, workdoc?, parent_task?}).</summary>
    [HttpPost("tasks")]
    public Task<IActionResult> Submit([FromBody] JsonElement body)
    {
        var dict = ToDict(body);
        dict["source"] = "ui";
        dict["requested_by"] = "user";
        return Wrap(() => _hub.RoutePostAsync(Svc, $"{Forge}/tasks", dict, 30));
    }

    [HttpGet("tasks/{id}")]
    public Task<IActionResult> GetTask(string id) => Wrap(() => _hub.RouteGetAsync(Svc, TaskPath(id)));

    [HttpGet("tasks/{id}/transcript")]
    public Task<IActionResult> Transcript(string id, [FromQuery] int offset = 0, [FromQuery] int limit = 500)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{TaskPath(id)}/transcript",
            new Dictionary<string, string> { ["offset"] = offset.ToString(), ["limit"] = limit.ToString() }, 30));

    [HttpGet("tasks/{id}/files")]
    public Task<IActionResult> Files(string id, [FromQuery] bool diff = true)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{TaskPath(id)}/files",
            new Dictionary<string, string> { ["diff"] = diff ? "true" : "false" }, 30));

    [HttpGet("tasks/{id}/{part:regex(^(workdoc|tests|logs|events)$)}")]
    public Task<IActionResult> Part(string id, string part)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{TaskPath(id)}/{part}", null, 30));

    /// <summary>approve | reject | rollback | retry, body {reason?, now?}; by is always "user".</summary>
    [HttpPost("tasks/{id}/{verb:regex(^(approve|reject|rollback|retry)$)}")]
    public Task<IActionResult> Act(string id, string verb, [FromBody] JsonElement? body = null)
    {
        var dict = body is JsonElement b ? ToDict(b) : new Dictionary<string, object?>();
        dict["by"] = "user";
        return Wrap(() => _hub.RoutePostAsync(Svc, $"{TaskPath(id)}/{verb}", dict, 60));
    }

    // ── Repository (read-only) ─────────────────────────────────────────

    [HttpGet("repo/{part:regex(^(branches|tags)$)}")]
    public Task<IActionResult> RepoList(string part) => Wrap(() => _hub.RouteGetAsync(Svc, $"{Repo}/{part}", null, 30));

    [HttpGet("repo/log")]
    public Task<IActionResult> RepoLog([FromQuery] string? @ref = null, [FromQuery] string? path = null,
        [FromQuery] int limit = 100, [FromQuery] int skip = 0, [FromQuery] bool all = false)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{Repo}/log", Query(("ref", @ref), ("path", path),
            ("limit", limit.ToString()), ("skip", skip.ToString()), ("all", all ? "true" : "false")), 30));

    [HttpGet("repo/commits/{sha}")]
    public Task<IActionResult> RepoCommit(string sha)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{Repo}/commits/{Uri.EscapeDataString(sha)}", null, 30));

    [HttpGet("repo/compare")]
    public Task<IActionResult> RepoCompare([FromQuery] string? @base = null, [FromQuery] string? head = null)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{Repo}/compare", Query(("base", @base), ("head", head)), 30));

    [HttpGet("repo/{part:regex(^(tree|file)$)}")]
    public Task<IActionResult> RepoFiles(string part, [FromQuery] string? @ref = null, [FromQuery] string? path = null)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{Repo}/{part}", Query(("ref", @ref), ("path", path)), 30));

    [HttpGet("repo/dossiers")]
    public Task<IActionResult> RepoDossiers([FromQuery] string? @ref = null)
        => Wrap(() => _hub.RouteGetAsync(Svc, $"{Repo}/dossiers", Query(("ref", @ref)), 30));

    // ── helpers ────────────────────────────────────────────────────────

    private static string TaskPath(string id) => $"{Forge}/tasks/{Uri.EscapeDataString(id)}";

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

    private async Task<IActionResult> Wrap(Func<Task<JsonElement>> call)
    {
        try
        {
            return Ok(await call());
        }
        catch (HttpRequestException ex)
        {
            _logger.LogWarning(ex, "event=webui_forge_call_failed");
            var code = ex.StatusCode is HttpStatusCode sc ? (int)sc : 502;
            return StatusCode(code >= 400 ? code : 502, new { detail = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=webui_forge_call_error");
            return StatusCode(502, new { detail = ex.Message });
        }
    }
}
