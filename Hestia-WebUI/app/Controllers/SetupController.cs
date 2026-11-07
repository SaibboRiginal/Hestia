namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Guided setup «Benvenuto» (SPEC docs/work/2026-10-30-setup-un-click §4.2). Thin proxy: browser → WebUI → Hub →
/// Hephaestus <c>/api/setup/*</c>, which writes the secrets and asks Oracle for the brain. Only the screens' paths
/// are forwarded: <c>telegram/claim</c> belongs to the bot, never to the browser.
/// </summary>
[ApiController]
[Route("api/webui/setup")]
public class SetupController : ControllerBase
{
    private const string Svc = "hephaestus";
    private static readonly HashSet<string> Gets = new() { "state", "brain/catalog", "brain/pulls", "voice/catalog", "machines", "tunnel", "update" };
    private static readonly HashSet<string> Posts = new()
    {
        "later", "complete", "brain/test", "brain/apply", "brain/pull", "voice/test", "voice/apply", "telegram/token", "telegram/code", "backup",
        "machines/pair", "machines/revoke", "machines/brain", "tunnel", "update/check", "update/apply", "update/back",
    };
    private readonly HubClient _hub;

    public SetupController(HubClient hub) => _hub = hub;

    [HttpGet("{**path}")]
    public Task<IActionResult> Get(string path)
        => Gets.Contains(path) ? Forward(HttpMethod.Get, path, null, 30, Hosts()) : Task.FromResult<IActionResult>(NotFound());

    /// <summary>The catalogs also look on other computers of the home network (<c>?hosts=192.168.1.20</c>): only that
    /// query key is passed on, the module checks each address.</summary>
    private Dictionary<string, string>? Hosts()
    {
        var hosts = Request.Query["hosts"].ToString();
        return string.IsNullOrWhiteSpace(hosts) ? null : new Dictionary<string, string> { ["hosts"] = hosts[..Math.Min(hosts.Length, 300)] };
    }

    /// <summary>A key test or a brain change re-creates Oracle and waits for it, the outside address may first
    /// download cloudflared, an update check fetches from GitHub: up to three minutes.</summary>
    [HttpPost("{**path}")]
    public Task<IActionResult> Post(string path, [FromBody] JsonElement? body = null)
        => Posts.Contains(path)
            ? Forward(HttpMethod.Post, path, body is JsonElement b ? b : new { }, path.StartsWith("brain/") || path.StartsWith("voice/") || path == "tunnel" || path.StartsWith("update/") ? 180 : 60)
            : Task.FromResult<IActionResult>(NotFound());

    private async Task<IActionResult> Forward(HttpMethod method, string path, object? body, double timeout,
        Dictionary<string, string>? query = null)
    {
        var (status, payload) = await _hub.RouteRawAsync(Svc, $"/api/setup/{path}", method, body, query, timeout,
            HttpContext.RequestAborted);
        return new ContentResult
        {
            StatusCode = status,
            ContentType = "application/json",
            Content = payload.ValueKind == JsonValueKind.Undefined ? "{}" : payload.GetRawText(),
        };
    }
}
