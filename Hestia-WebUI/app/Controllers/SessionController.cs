namespace Hestia.WebUI.Controllers;

using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Models;
using Hestia.WebUI.Services;

[ApiController]
[Route("api/webui/sessions")]
public class SessionController : ControllerBase
{
    private readonly SessionManager _sessionManager;
    private readonly HubClient _hubClient;
    private readonly ILogger<SessionController> _logger;

    public SessionController(
        SessionManager sessionManager,
        HubClient hubClient,
        ILogger<SessionController> logger)
    {
        _sessionManager = sessionManager;
        _hubClient = hubClient;
        _logger = logger;
    }

    [HttpGet("current")]
    public IActionResult GetCurrent()
    {
        return Ok(new SessionInfo(_sessionManager.GetSession()));
    }

    [HttpPost("clear")]
    public async Task<IActionResult> Clear()
    {
        var newId = await _sessionManager.ResetSessionAsync(_hubClient);
        _logger.LogInformation("event=webui_session_cleared");
        return Ok(new SessionCleared("ok", newId));
    }
}
