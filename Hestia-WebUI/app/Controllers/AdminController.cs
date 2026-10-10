namespace Hestia.WebUI.Controllers;

using System.Net;
using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;
using Hestia.WebUI.Services;

/// <summary>
/// Admin guard. Port 19015 is published and tunneled by Cloudflare, so "internal only"
/// must be enforced: with <c>WEBUI_ADMIN_SECRET</c> set, the header
/// <c>X-WebUI-Admin-Secret</c> must match; without it, only direct requests from
/// loopback/private addresses (Docker network, LAN, the tunnel script on the host)
/// that did not come through a proxy/tunnel are accepted.
/// </summary>
public sealed class AdminGuardAttribute : ActionFilterAttribute
{
    public override void OnActionExecuting(ActionExecutingContext context)
    {
        var req = context.HttpContext.Request;
        var secret = Environment.GetEnvironmentVariable("WEBUI_ADMIN_SECRET") ?? "";
        bool allowed;
        if (secret.Length > 0)
        {
            var given = req.Headers["X-WebUI-Admin-Secret"].FirstOrDefault() ?? "";
            allowed = CryptographicOperations.FixedTimeEquals(
                Encoding.UTF8.GetBytes(given), Encoding.UTF8.GetBytes(secret));
        }
        else
        {
            var proxied = req.Headers.ContainsKey("Cf-Connecting-Ip") || req.Headers.ContainsKey("Cf-Ray")
                          || req.Headers.ContainsKey("X-Forwarded-For");
            allowed = !proxied && IsPrivate(context.HttpContext.Connection.RemoteIpAddress);
        }
        if (!allowed)
            context.Result = new ObjectResult(new { error = "admin endpoint: forbidden" }) { StatusCode = 403 };
    }

    internal static bool IsPrivate(IPAddress? ip)
    {
        if (ip is null) return false;
        if (ip.IsIPv4MappedToIPv6) ip = ip.MapToIPv4();
        if (IPAddress.IsLoopback(ip)) return true;
        var b = ip.GetAddressBytes();
        if (b.Length == 4)
            return b[0] == 10 || (b[0] == 172 && b[1] >= 16 && b[1] <= 31) || (b[0] == 192 && b[1] == 168);
        return ip.IsIPv6LinkLocal || ip.IsIPv6UniqueLocal;
    }
}

/// <summary>
/// Internal-network guard for service-to-service callbacks reached through Hub (e.g. Hermes
/// → <c>/api/notify</c>): only direct requests from loopback/private addresses that did not
/// come through a proxy/tunnel. No shared secret (Hub routes plain envelopes).
/// </summary>
public sealed class InternalNetworkGuardAttribute : ActionFilterAttribute
{
    public override void OnActionExecuting(ActionExecutingContext context)
    {
        var req = context.HttpContext.Request;
        var proxied = req.Headers.ContainsKey("Cf-Connecting-Ip") || req.Headers.ContainsKey("Cf-Ray")
                      || req.Headers.ContainsKey("X-Forwarded-For");
        if (proxied || !AdminGuardAttribute.IsPrivate(context.HttpContext.Connection.RemoteIpAddress))
            context.Result = new ObjectResult(new { error = "internal endpoint: forbidden" }) { StatusCode = 403 };
    }
}

/// <summary>
/// Admin API for WebUI token lifecycle management + public URL.
/// Guarded by <see cref="AdminGuardAttribute"/> (internal network or shared secret) — NOT routed through Hub.
/// Called directly by Telegram at http://hestia_webui:19015.
/// </summary>
[ApiController]
[AdminGuard]
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
