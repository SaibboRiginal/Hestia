namespace Hestia.WebUI.Controllers;

using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Models;
using Hestia.WebUI.Services;

[ApiController]
[Route("api/webui/auth")]
public class AuthController : ControllerBase
{
    private readonly TokenManager _tokenManager;
    private readonly LocalAccess _localAccess;
    private readonly ILogger<AuthController> _logger;

    public AuthController(TokenManager tokenManager, LocalAccess localAccess, ILogger<AuthController> logger)
    {
        _tokenManager = tokenManager;
        _localAccess = localAccess;
        _logger = logger;
    }

    /// <summary>
    /// Asked by the browser at start (no token needed): home network → no login page;
    /// through the Cloudflare tunnel (or with the switch off) → token required.
    /// </summary>
    [HttpGet("access")]
    public IActionResult Access()
    {
        var reason = _localAccess.Reason(HttpContext);
        var local = reason == "local";
        _logger.LogInformation("event=webui_access_checked local={Local} reason={Reason} peer={Peer} host={Host}",
            local, reason, HttpContext.Connection.RemoteIpAddress, HttpContext.Request.Host.Host);
        // reason = local | setting_off | proxied | public_host | public_address (diagnosis, no secrets)
        return Ok(new { local, tokenRequired = !local, reason });
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
