namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Assistant presence for the browser (SPEC docs/work/2026-10-10-assistant-presence): current state
/// (badge in the sidebar) and «Non disturbare». Thin proxy: browser → WebUI → Hub → Chronos.
/// </summary>
[ApiController]
[Route("api/webui/presence")]
public class PresenceController : ControllerBase
{
    private const string Svc = "chronos";
    private readonly HubClient _hub;

    public PresenceController(HubClient hub) => _hub = hub;

    [HttpGet]
    public Task<IActionResult> State() => Forward(HttpMethod.Get, "/api/presence");

    [HttpGet("history")]
    public Task<IActionResult> History([FromQuery] int limit = 20)
        => Forward(HttpMethod.Get, "/api/presence/history",
            query: new Dictionary<string, string> { ["limit"] = Math.Clamp(limit, 1, 200).ToString() });

    /// <summary>Body {minutes?, until?}: empty = the default duration (setting).</summary>
    [HttpPost("dnd")]
    public Task<IActionResult> DndOn([FromBody] JsonElement? body = null)
        => Forward(HttpMethod.Post, "/api/presence/dnd", body is JsonElement b ? b : new { });

    [HttpDelete("dnd")]
    public Task<IActionResult> DndOff() => Forward(HttpMethod.Delete, "/api/presence/dnd");

    private async Task<IActionResult> Forward(HttpMethod method, string path, object? body = null,
        Dictionary<string, string>? query = null)
    {
        var (status, payload) = await _hub.RouteRawAsync(Svc, path, method, body, query, 10);
        return new ContentResult
        {
            StatusCode = status,
            ContentType = "application/json",
            Content = payload.ValueKind == JsonValueKind.Undefined ? "{}" : payload.GetRawText(),
        };
    }
}
