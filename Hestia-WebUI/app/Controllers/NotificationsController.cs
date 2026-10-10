namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.SignalR;
using Hestia.WebUI.Hubs;
using Hestia.WebUI.Services;

/// <summary>
/// WebUI as a Hermes notification client (SPEC hermes-global-notifications).
/// <list type="bullet">
/// <item><c>POST /api/notify</c> — Hermes (via Hub, internal network only) pushes
/// <c>notification</c> / <c>update</c> / <c>retract</c>; forwarded live to every open browser
/// on SignalR (<c>ReceiveNotification</c>). The inbox lives in Archive (through Hermes), so a
/// closed WebUI loses nothing.</item>
/// <item><c>/api/webui/notifications*</c> — token-protected proxy to Hermes for the page.</item>
/// </list>
/// </summary>
[ApiController]
public class NotificationsController : ControllerBase
{
    private const string ClientName = "webui";
    private readonly HubClient _hub;
    private readonly IHubContext<ChatHub> _browsers;
    private readonly ILogger<NotificationsController> _logger;

    public NotificationsController(HubClient hub, IHubContext<ChatHub> browsers, ILogger<NotificationsController> logger)
    {
        _hub = hub;
        _browsers = browsers;
        _logger = logger;
    }

    [HttpPost("api/notify")]
    [InternalNetworkGuard]
    public async Task<IActionResult> Notify([FromBody] JsonElement body)
    {
        var kind = body.TryGetProperty("kind", out var k) ? k.GetString() ?? "notification" : "notification";
        var id = body.TryGetProperty("notification_id", out var n) ? n.GetString() : null;
        if (kind == "retract")
            return Ok(new { status = "ok", deleted = false }); // the inbox keeps everything
        await _browsers.Clients.All.SendAsync("ReceiveNotification", body);
        _logger.LogInformation("event=notification_pushed kind={Kind} notification_id={Id}", kind, id);
        return Ok(new { delivered = true });
    }

    [HttpGet("api/webui/notifications")]
    public Task<IActionResult> List([FromQuery] string filter = "all", [FromQuery] string? source = null,
        [FromQuery] string? before = null, [FromQuery] int limit = 50)
    {
        var q = new Dictionary<string, string>
        {
            ["filter"] = filter, ["limit"] = Math.Clamp(limit, 1, 200).ToString(), ["client"] = ClientName,
        };
        if (!string.IsNullOrWhiteSpace(source)) q["source"] = source;
        if (!string.IsNullOrWhiteSpace(before)) q["before"] = before;
        return Forward(HttpMethod.Get, "/api/notifications", null, q);
    }

    [HttpGet("api/webui/notifications/counts")]
    public Task<IActionResult> Counts()
        => Forward(HttpMethod.Get, "/api/notifications/counts", null,
            new Dictionary<string, string> { ["client"] = ClientName });

    [HttpPost("api/webui/notifications/seen-all")]
    public Task<IActionResult> SeenAll()
        => Forward(HttpMethod.Post, "/api/notifications/seen-all", new { client = ClientName });

    [HttpPost("api/webui/notifications/{id}/seen")]
    public Task<IActionResult> Seen(string id)
        => Forward(HttpMethod.Post, $"/api/notifications/{Uri.EscapeDataString(id)}/seen", new { client = ClientName });

    /// <summary>Answer with one of the notification's buttons; 409 = already handled elsewhere.</summary>
    [HttpPost("api/webui/notifications/{id}/answer")]
    public Task<IActionResult> Answer(string id, [FromBody] AnswerRequest req)
        => Forward(HttpMethod.Post, $"/api/notifications/{Uri.EscapeDataString(id)}/answer",
            new { action_id = req.ActionId, client = ClientName }, timeoutSeconds: 30);

    private async Task<IActionResult> Forward(HttpMethod method, string path, object? body = null,
        Dictionary<string, string>? query = null, double timeoutSeconds = 20)
    {
        var (status, payload) = await _hub.RouteRawAsync("hermes", path, method, body, query, timeoutSeconds);
        return new ContentResult
        {
            StatusCode = status,
            ContentType = "application/json",
            Content = payload.ValueKind == JsonValueKind.Undefined ? "{}" : payload.GetRawText(),
        };
    }

    public record AnswerRequest(string ActionId);
}
