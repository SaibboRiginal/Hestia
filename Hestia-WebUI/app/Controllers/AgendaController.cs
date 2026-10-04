namespace Hestia.WebUI.Controllers;

using System.Net;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Assistant agenda (Hestia's own calendar) for the WebUI calendar module.
/// Thin proxy: browser → WebUI → Hub → Chronos /api/agenda*. Token-protected by the middleware.
/// </summary>
[ApiController]
[Route("api/webui/agenda")]
public class AgendaController : ControllerBase
{
    private readonly HubClient _hub;
    private readonly ILogger<AgendaController> _logger;

    public AgendaController(HubClient hub, ILogger<AgendaController> logger)
    {
        _hub = hub;
        _logger = logger;
    }

    /// <summary>Occurrences in [start, end).</summary>
    [HttpGet("occurrences")]
    public Task<IActionResult> Occurrences([FromQuery] string start, [FromQuery] string end,
        [FromQuery] string? owner = null, [FromQuery] string? type = null, [FromQuery] bool includeDone = true)
    {
        var q = new Dictionary<string, string> { ["start"] = start, ["end"] = end, ["include_done"] = includeDone ? "true" : "false" };
        if (!string.IsNullOrWhiteSpace(owner)) q["owner"] = owner;
        if (!string.IsNullOrWhiteSpace(type)) q["type"] = type;
        return Wrap(() => _hub.RouteGetAsync("chronos", "/api/agenda", q, 20));
    }

    [HttpGet("items")]
    public Task<IActionResult> Items([FromQuery] bool includeCancelled = true)
        => Wrap(() => _hub.RouteGetAsync("chronos", "/api/agenda/items",
            new Dictionary<string, string> { ["include_cancelled"] = includeCancelled ? "true" : "false" }));

    [HttpPost("items")]
    public Task<IActionResult> Create([FromBody] JsonElement body)
        => Wrap(() => _hub.RoutePostAsync("chronos", "/api/agenda/items", WithUser(body)));

    [HttpPatch("items/{itemRef}")]
    public Task<IActionResult> Update(string itemRef, [FromBody] JsonElement body)
        => Wrap(() => _hub.RouteAsyncPublic("chronos", $"/api/agenda/items/{Uri.EscapeDataString(itemRef)}",
            HttpMethod.Patch, WithBy(body)));

    [HttpDelete("items/{itemRef}")]
    public Task<IActionResult> Cancel(string itemRef)
        => Wrap(() => _hub.RouteAsyncPublic("chronos", $"/api/agenda/items/{Uri.EscapeDataString(itemRef)}",
            HttpMethod.Delete, null, new Dictionary<string, string> { ["by"] = "user" }));

    [HttpPost("items/{itemRef}/skip")]
    public Task<IActionResult> Skip(string itemRef, [FromBody] JsonElement body)
        => Wrap(() => _hub.RoutePostAsync("chronos", $"/api/agenda/items/{Uri.EscapeDataString(itemRef)}/skip", WithBy(body)));

    [HttpPost("items/{itemRef}/unskip")]
    public Task<IActionResult> Unskip(string itemRef, [FromBody] JsonElement body)
        => Wrap(() => _hub.RoutePostAsync("chronos", $"/api/agenda/items/{Uri.EscapeDataString(itemRef)}/unskip", WithBy(body)));

    /// <summary>Move one occurrence (exception) or reset it ({occurrence, start_at, end_at, reset}).</summary>
    [HttpPost("items/{itemRef}/move")]
    public Task<IActionResult> Move(string itemRef, [FromBody] JsonElement body)
        => Wrap(() => _hub.RoutePostAsync("chronos", $"/api/agenda/items/{Uri.EscapeDataString(itemRef)}/move", WithBy(body)));

    [HttpPost("items/{itemRef}/run")]
    public Task<IActionResult> Run(string itemRef)
        => Wrap(() => _hub.RoutePostAsync("chronos", $"/api/agenda/items/{Uri.EscapeDataString(itemRef)}/run", new { }, 60));

    /// <summary>What each module lets the user create (calendar wizard).</summary>
    [HttpGet("templates")]
    public Task<IActionResult> Templates()
        => Wrap(() => _hub.RouteGetAsync("chronos", "/api/agenda/templates", new Dictionary<string, string>()));

    /// <summary>Create from a module template ({values, start_at, end_at?, recurrence?, type?, description?}).</summary>
    [HttpPost("templates/{owner}/{templateId}/create")]
    public Task<IActionResult> CreateFromTemplate(string owner, string templateId, [FromBody] JsonElement body)
        => Wrap(() => _hub.RoutePostAsync("chronos",
            $"/api/agenda/templates/{Uri.EscapeDataString(owner)}/{Uri.EscapeDataString(templateId)}/create", ToDict(body)));

    // ── helpers ──────────────────────────────────────────────────────────

    /// <summary>Edits from the WebUI are user decisions: Chronos marks them user_modified.</summary>
    private static Dictionary<string, object?> WithBy(JsonElement body)
    {
        var d = ToDict(body);
        d["by"] = "user";
        return d;
    }

    private static Dictionary<string, object?> WithUser(JsonElement body)
    {
        var d = ToDict(body);
        if (!d.ContainsKey("created_by")) d["created_by"] = "user";
        if (!d.ContainsKey("owner")) d["owner"] = "user";
        return d;
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
            _logger.LogWarning(ex, "event=webui_agenda_call_failed");
            var code = ex.StatusCode is HttpStatusCode sc ? (int)sc : 502;
            return StatusCode(code >= 400 ? code : 502, new { detail = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=webui_agenda_call_error");
            return StatusCode(502, new { detail = ex.Message });
        }
    }
}
