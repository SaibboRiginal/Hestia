namespace Hestia.WebUI.Controllers;

using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Models;
using Hestia.WebUI.Services;

[ApiController]
[Route("api/webui/feedback")]
public class FeedbackController : ControllerBase
{
    private readonly HubClient _hubClient;
    private readonly SessionManager _sessionManager;
    private readonly ILogger<FeedbackController> _logger;

    public FeedbackController(HubClient hubClient, SessionManager sessionManager, ILogger<FeedbackController> logger)
    {
        _hubClient = hubClient;
        _sessionManager = sessionManager;
        _logger = logger;
    }

    [HttpPost]
    public async Task<IActionResult> Submit([FromBody] FeedbackRequest req)
    {
        var label = req.QualityLabel?.Trim().ToLowerInvariant() ?? "";
        if (label is not ("good" or "bad"))
            return BadRequest(new FeedbackResponse(false));

        var qualityScore = req.QualityScore ?? (label == "good" ? 4 : 2);
        var sessionId = _sessionManager.GetSession();

        try
        {
            await _hubClient.RoutePostAsync("archive", "/api/feedback", new
            {
                session_id = sessionId,
                interaction_id = req.InteractionId,
                quality_label = label == "good" ? "good" : "poor",
                quality_score = qualityScore,
                feedback_text = req.FeedbackText,
                source_client = "webui",
                tags = new[] { "webui" },
                payload = new { instruction = req.Prompt ?? "", output = req.Response ?? "" }
            });
            _logger.LogInformation("event=webui_feedback_submitted label={Label} score={Score}",
                label, qualityScore);
            return Ok(new FeedbackResponse(true));
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=webui_feedback_failed");
            return Ok(new FeedbackResponse(false));
        }
    }
}
