namespace Hestia.WebUI.Controllers;

using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Admin API for WebUI token lifecycle management + public URL.
/// ONLY accessible within the internal Docker network — NOT routed through Hub.
/// Called directly by Telegram at http://hestia_webui:19015.
/// </summary>
[ApiController]
[Route("api/webui/admin")]
public class AdminController : ControllerBase
{
    private readonly TokenManager _tokenManager;
    private readonly HubClient _hubClient;
    private readonly PublicUrlService _publicUrl;
    private readonly ILogger<AdminController> _logger;

    public AdminController(
        TokenManager tokenManager,
        HubClient hubClient,
        PublicUrlService publicUrl,
        ILogger<AdminController> logger)
    {
        _tokenManager = tokenManager;
        _hubClient = hubClient;
        _publicUrl = publicUrl;
        _logger = logger;
    }

    [HttpPost("generate-token")]
    public IActionResult GenerateToken([FromQuery] double? lifetimeHours = null)
    {
        var token = _tokenManager.GenerateToken();
        var hours = lifetimeHours ?? 72;
        _tokenManager.SetActiveToken(token, hours);
        _ = _tokenManager.PersistTokenAsync(token, _hubClient);

        var status = _tokenManager.GetTokenStatus();
        var publicUrl = _publicUrl.GetPublicUrl();

        _logger.LogInformation("event=webui_admin_token_generated hours={Hours}", hours);

        return Ok(new
        {
            token,
            public_url = publicUrl,
            expires_at = status.ExpiresAt,
            expires_in_seconds = status.RemainingSeconds,
            lifetime_hours = hours,
        });
    }

    [HttpPost("revoke-token")]
    public IActionResult RevokeToken()
    {
        _tokenManager.RevokeToken();
        _ = _tokenManager.PersistTokenAsync(null, _hubClient, action: "revoke");
        _logger.LogInformation("event=webui_admin_token_revoked");
        return Ok(new { status = "revoked" });
    }

    [HttpGet("token-status")]
    public IActionResult TokenStatus()
    {
        var status = _tokenManager.GetTokenStatus();
        return Ok(new
        {
            active = status.Active,
            created_at = status.CreatedAt,
            expires_at = status.ExpiresAt,
            remaining_seconds = status.RemainingSeconds,
            remaining_hours = status.RemainingHours,
        });
    }

    /// <summary>Get the current public-facing URL (auto-detected from Cloudflare tunnel).</summary>
    [HttpGet("public-url")]
    public IActionResult GetPublicUrl()
    {
        var url = _publicUrl.GetPublicUrl();
        return Ok(new
        {
            public_url = url,
            detected = url is not null,
        });
    }

    /// <summary>Manually set the public URL (e.g. from a startup script).</summary>
    [HttpPost("public-url")]
    public IActionResult SetPublicUrl([FromBody] SetPublicUrlRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.Url))
            return BadRequest(new { error = "url is required" });

        _publicUrl.SetPublicUrl(req.Url.Trim());
        _logger.LogInformation("event=public_url_manual_set url={Url}", req.Url);

        return Ok(new { public_url = req.Url, detected = true });
    }
}

public record SetPublicUrlRequest(string Url);
