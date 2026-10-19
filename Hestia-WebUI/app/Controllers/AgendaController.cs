namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Read-only ICS feed of the assistant agenda, for phone calendars. The Agenda page itself is Chronos's
/// plugin (/p/chronos/agenda, calls go through the plugin proxy); only the feed stays here because phones
/// fetch it with ?key=WEBUI_ICS_KEY instead of a WebUI token. Browser → WebUI → Hub → Chronos /api/agenda/ics.
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
}
