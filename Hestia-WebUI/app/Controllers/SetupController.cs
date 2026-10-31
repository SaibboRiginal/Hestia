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
    private static readonly HashSet<string> Gets = new() { "state", "brain/catalog", "brain/pulls" };
    private static readonly HashSet<string> Posts = new()
    {
        "later", "complete", "brain/test", "brain/apply", "brain/pull", "telegram/token", "telegram/code", "backup",
    };
    private readonly HubClient _hub;

    public SetupController(HubClient hub) => _hub = hub;

    [HttpGet("{**path}")]
    public Task<IActionResult> Get(string path)
        => Gets.Contains(path) ? Forward(HttpMethod.Get, path, null, 30) : Task.FromResult<IActionResult>(NotFound());

    /// <summary>A key test or a brain change re-creates Oracle and waits for it: up to two minutes.</summary>
    [HttpPost("{**path}")]
    public Task<IActionResult> Post(string path, [FromBody] JsonElement? body = null)
        => Posts.Contains(path)
            ? Forward(HttpMethod.Post, path, body is JsonElement b ? b : new { }, path.StartsWith("brain/") ? 180 : 60)
            : Task.FromResult<IActionResult>(NotFound());

    private async Task<IActionResult> Forward(HttpMethod method, string path, object? body, double timeout)
    {
        var (status, payload) = await _hub.RouteRawAsync(Svc, $"/api/setup/{path}", method, body, null, timeout,
            HttpContext.RequestAborted);
        return new ContentResult
        {
            StatusCode = status,
            ContentType = "application/json",
            Content = payload.ValueKind == JsonValueKind.Undefined ? "{}" : payload.GetRawText(),
        };
    }
}
