namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Public door of Hestia's MCP for external AIs (Claude Code, Claude Desktop, Cursor…): <c>/mcp</c> on the WebUI,
/// the only service behind the Cloudflare tunnel. Not under /api/webui, so the WebUI login does not apply: the
/// request goes as is (body + <c>Authorization: Bearer</c>) through Hub to Hestia-MCP <c>/mcp/external</c>, which
/// checks the access token (401), the rate limit (429) and the scope (403).
/// SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2.
/// </summary>
[ApiController]
[Route("mcp")]
public class McpDoorController : ControllerBase
{
    private const int MaxBodyBytes = 1_000_000;
    private readonly HubClient _hubClient;
    private readonly ILogger<McpDoorController> _logger;

    public McpDoorController(HubClient hubClient, ILogger<McpDoorController> logger)
    {
        _hubClient = hubClient;
        _logger = logger;
    }

    [HttpPost]
    [RequestSizeLimit(MaxBodyBytes)]
    public async Task<IActionResult> Post(CancellationToken ct)
    {
        var auth = Request.Headers.Authorization.FirstOrDefault() ?? "";
        if (!auth.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase))
            return Unauthorized401("Missing bearer token");

        JsonElement body;
        try
        {
            body = await JsonSerializer.DeserializeAsync<JsonElement>(Request.Body, cancellationToken: ct);
        }
        catch (JsonException)
        {
            return StatusCode(400, new { jsonrpc = "2.0", id = (object?)null, error = new { code = -32700, message = "Parse error" } });
        }

        // Within the HubClient's own 30 s: external tools are quick reads or queue a job (Forge runs it later).
        var (status, payload) = await _hubClient.RouteRawAsync("mcp", "mcp/external", HttpMethod.Post, body,
            timeoutSeconds: 25, ct: ct, headers: new Dictionary<string, string> { ["Authorization"] = auth });
        _logger.LogInformation("event=mcp_door_call status={Status}", status);

        if (status == 202) return StatusCode(202);
        if (status == 401) return Unauthorized401(null, payload);
        if (status == 429) Response.Headers.RetryAfter = "60";
        return new ContentResult
        {
            StatusCode = status,
            ContentType = "application/json",
            Content = payload.ValueKind == JsonValueKind.Undefined ? "{}" : payload.GetRawText(),
        };
    }

    /// <summary>No server-initiated stream (Streamable HTTP allows 405); sessions are not used.</summary>
    [HttpGet]
    [HttpDelete]
    public IActionResult NotAllowed()
    {
        Response.Headers.Allow = "POST";
        return StatusCode(405);
    }

    private IActionResult Unauthorized401(string? message, JsonElement? payload = null)
    {
        Response.Headers.WWWAuthenticate = "Bearer";
        if (payload is { ValueKind: JsonValueKind.Object } p)
            return new ContentResult { StatusCode = 401, ContentType = "application/json", Content = p.GetRawText() };
        return StatusCode(401, new { jsonrpc = "2.0", id = (object?)null, error = new { code = -32001, message } });
    }
}
