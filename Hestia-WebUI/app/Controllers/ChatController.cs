namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// REST-based document upload endpoint for file analysis, plus the chat header's context gauge
/// (window use + this conversation's consumption, from Oracle via the Hub) and "Compatta".
/// For text chat, use SignalR ChatHub (/hubs/chat).
/// </summary>
[ApiController]
[Route("api/webui/chat")]
public class ChatController : ControllerBase
{
    private readonly OracleStreamService _oracleStream;
    private readonly SessionManager _sessionManager;
    private readonly HubClient _hub;
    private readonly ILogger<ChatController> _logger;

    public ChatController(OracleStreamService oracleStream, SessionManager sessionManager, HubClient hub,
        ILogger<ChatController> logger)
    {
        _oracleStream = oracleStream;
        _sessionManager = sessionManager;
        _hub = hub;
        _logger = logger;
    }

    /// <summary>Context window use of the current conversation + provider in use + its consumption.</summary>
    [HttpGet("context")]
    public async Task<IActionResult> Context()
    {
        var (status, payload) = await _hub.RouteRawAsync("oracle", "/api/chat/context", HttpMethod.Get,
            query: new Dictionary<string, string> { ["session_id"] = _sessionManager.GetSession() }, timeoutSeconds: 15);
        return StatusCode(status, payload);
    }

    /// <summary>Summarise older messages of the current conversation (frees context).</summary>
    [HttpPost("compact")]
    public async Task<IActionResult> Compact()
    {
        var sid = _sessionManager.GetSession();
        _logger.LogInformation("event=webui_chat_compact session={S}", sid);
        var (status, payload) = await _hub.RouteRawAsync("oracle", "/api/chat/compact", HttpMethod.Post,
            query: new Dictionary<string, string> { ["session_id"] = sid }, timeoutSeconds: 120);
        return StatusCode(status, payload);
    }

    [HttpPost("document")]
    [RequestSizeLimit(52_428_800)] // 50 MB
    public async Task<IActionResult> UploadDocument(
        IFormFile file,
        [FromForm] string message = "Analizza questo documento.",
        [FromForm] string? sessionId = null)
    {
        if (file is null || file.Length == 0)
            return BadRequest(new { detail = "No file provided" });

        var mimeType = (file.ContentType ?? "application/octet-stream")
            .Split(';')[0].Trim().ToLowerInvariant();

        var isTextLike = mimeType.StartsWith("text/") || mimeType is
            "application/json" or "application/xml" or "application/yaml" or "application/x-yaml";

        if (!OracleStreamService.AcceptedMimes.Contains(mimeType) && !isTextLike)
            return BadRequest(new { detail = $"Unsupported file type: {mimeType}" });

        var sid = string.IsNullOrWhiteSpace(sessionId)
            ? _sessionManager.GetOrCreateSession()
            : sessionId;

        _logger.LogInformation("event=webui_document_upload file={File} mime={Mime} size={Size}",
            file.FileName, mimeType, file.Length);

        using var ms = new MemoryStream();
        await file.CopyToAsync(ms);
        var bytes = ms.ToArray();

        var clientInstructions = _sessionManager.BuildClientInstructions();

        Response.ContentType = "application/x-ndjson";
        Response.Headers["Cache-Control"] = "no-cache";
        Response.Headers["X-Content-Type-Options"] = "nosniff";

        await foreach (var evt in _oracleStream.StreamDocumentAsync(
            bytes, file.FileName ?? "document", mimeType,
            message, sid, clientInstructions))
        {
            var json = JsonSerializer.Serialize(evt,
                new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
            await Response.WriteAsync(json + "\n");
            await Response.Body.FlushAsync();
        }

        return new EmptyResult();
    }
}
