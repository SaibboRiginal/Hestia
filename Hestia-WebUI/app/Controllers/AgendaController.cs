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

    /// <summary>Natural-language quick add → draft for the editor (Chronos asks Oracle; nothing is created).</summary>
    [HttpPost("parse")]
    public Task<IActionResult> Parse([FromBody] JsonElement body)
        => Wrap(() => _hub.RoutePostAsync("chronos", "/api/agenda/parse", ToDict(body), 60));

    /// <summary>
    /// Read-only ICS feed (phones). Auth: normal token, or ?key= matching WEBUI_ICS_KEY
    /// (the middleware lets that one path through; the key grants nothing else).
    /// </summary>
    [HttpGet("feed.ics")]
    public async Task<IActionResult> Feed([FromQuery] int days = 60, [FromQuery] string? owner = null,
        [FromQuery] string types = "event,task,window")
    {
        var q = new Dictionary<string, string> { ["days"] = Math.Clamp(days, 1, 400).ToString(), ["types"] = types };
        if (!string.IsNullOrWhiteSpace(owner)) q["owner"] = owner;
        try
        {
            var res = await _hub.RouteGetAsync("chronos", "/api/agenda/ics", q, 30);
            // Hub wraps non-JSON payloads as {"raw": "..."}.
            var text = res.ValueKind == JsonValueKind.Object && res.TryGetProperty("raw", out var raw)
                ? raw.GetString() ?? "" : res.ValueKind == JsonValueKind.String ? res.GetString() ?? "" : "";
            if (!text.StartsWith("BEGIN:VCALENDAR"))
                return StatusCode(502, new { detail = "Chronos did not return a calendar" });
            return File(System.Text.Encoding.UTF8.GetBytes(text), "text/calendar; charset=utf-8", "hestia-agenda.ics");
        }
        catch (HttpRequestException ex)
        {
            _logger.LogWarning(ex, "event=webui_agenda_ics_failed");
            return StatusCode(502, new { detail = ex.Message });
        }
    }

    /// <summary>Feed URL for the calendar's "Abbonati" dialog (key only when configured).</summary>
    [HttpGet("feed-info")]
    public IActionResult FeedInfo()
    {
        var key = Environment.GetEnvironmentVariable("WEBUI_ICS_KEY") ?? "";
        return Ok(new { keyConfigured = key.Length >= 16, path = "/api/webui/agenda/feed.ics", key = key.Length >= 16 ? key : null });
    }

    /// <summary>
    /// Logs of a service around an occurrence ("Log" link): GET {svc}/api/logs (in-memory buffer,
    /// last ~2000 lines) filtered to at ± minutes. Optional contains (e.g. the item key).
    /// </summary>
    [HttpGet("logs")]
    public async Task<IActionResult> Logs([FromQuery] string service, [FromQuery] string at,
        [FromQuery] int minutes = 5, [FromQuery] string? level = null, [FromQuery] string? contains = null)
    {
        if (string.IsNullOrWhiteSpace(service) || !System.Text.RegularExpressions.Regex.IsMatch(service, "^[a-z0-9_-]{2,40}$"))
            return BadRequest(new { detail = "invalid service" });
        if (!DateTimeOffset.TryParse(at, out var center))
            return BadRequest(new { detail = "at must be an ISO datetime" });
        minutes = Math.Clamp(minutes, 1, 120);
        var lo = center.AddMinutes(-minutes);
        var hi = center.AddMinutes(minutes);
        var q = new Dictionary<string, string> { ["limit"] = "2000" };
        if (!string.IsNullOrWhiteSpace(level)) q["level"] = level;
        if (!string.IsNullOrWhiteSpace(contains)) q["contains"] = contains;
        try
        {
            var res = await _hub.RouteGetAsync(service, "/api/logs", q, 15);
            var rows = new List<JsonElement>();
            string? oldest = null;
            if (res.ValueKind == JsonValueKind.Object && res.TryGetProperty("logs", out var logs) && logs.ValueKind == JsonValueKind.Array)
            {
                foreach (var row in logs.EnumerateArray())
                {
                    if (!row.TryGetProperty("ts", out var tsEl) || !DateTimeOffset.TryParse(tsEl.GetString(), out var ts)) continue;
                    oldest ??= tsEl.GetString();
                    if (ts >= lo && ts <= hi) rows.Add(row);
                }
            }
            return Ok(new { service, from = lo, to = hi, count = rows.Count, oldest, logs = rows });
        }
        catch (HttpRequestException ex)
        {
            _logger.LogWarning(ex, "event=webui_agenda_logs_failed service={Service}", service);
            var code = ex.StatusCode is HttpStatusCode sc ? (int)sc : 502;
            return StatusCode(code >= 400 ? code : 502, new { detail = ex.Message });
        }
    }

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
