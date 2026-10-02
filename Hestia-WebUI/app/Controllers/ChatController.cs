namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// REST-based document upload endpoint for file analysis.
/// For text chat, use SignalR ChatHub (/hubs/chat).
/// </summary>
[ApiController]
[Route("api/webui/chat")]
public class ChatController : ControllerBase
{
    private readonly OracleStreamService _oracleStream;
    private readonly SessionManager _sessionManager;
    private readonly ILogger<ChatController> _logger;

    public ChatController(OracleStreamService oracleStream, SessionManager sessionManager, ILogger<ChatController> logger)
    {
        _oracleStream = oracleStream;
        _sessionManager = sessionManager;
        _logger = logger;
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
