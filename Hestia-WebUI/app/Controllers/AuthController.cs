namespace Hestia.WebUI.Controllers;

using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Models;
using Hestia.WebUI.Services;

[ApiController]
[Route("api/webui/auth")]
public class AuthController : ControllerBase
{
    private readonly TokenManager _tokenManager;
    private readonly ILogger<AuthController> _logger;

    public AuthController(TokenManager tokenManager, ILogger<AuthController> logger)
    {
        _tokenManager = tokenManager;
        _logger = logger;
    }

    [HttpPost("login")]
    public IActionResult Login([FromBody] LoginRequest request)
    {
        var token = request.Token?.Trim() ?? "";
        if (string.IsNullOrEmpty(token))
            return BadRequest(new { detail = "Token is required" });

        if (!_tokenManager.ValidateToken(token))
        {
            _logger.LogWarning("event=webui_login_failed ip={Ip}",
                HttpContext.Connection.RemoteIpAddress);
            return Unauthorized(new { detail = "Invalid or expired token" });
        }

        var status = _tokenManager.GetTokenStatus();
        _logger.LogInformation("event=webui_login_success ip={Ip} remaining_hours={H}",
            HttpContext.Connection.RemoteIpAddress, status.RemainingHours);

        return Ok(new LoginResponse("ok", status.RemainingSeconds));
    }

    [HttpGet("status")]
    public IActionResult Status()
    {
        return Ok(_tokenManager.GetTokenStatus());
    }
}
