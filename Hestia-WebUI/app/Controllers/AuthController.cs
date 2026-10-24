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
    private readonly HubClient _hub;
    private readonly ILogger<AuthController> _logger;

    public AuthController(TokenManager tokenManager, LocalAccess localAccess, HubClient hub, ILogger<AuthController> logger)
    {
        _tokenManager = tokenManager;
        _localAccess = localAccess;
        _hub = hub;
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

    /// <summary>
    /// Mini App login: the page opened inside Telegram sends Telegram's signed launch data (initData). The Telegram
    /// module checks the signature with its bot token and that the user is the owner (via Hub); then this returns a
    /// session token for 12 hours. The main /webui_token stays as it is.
    /// </summary>
    [HttpPost("telegram")]
    public async Task<IActionResult> TelegramLogin([FromBody] TelegramLoginRequest request, CancellationToken ct)
    {
        var initData = request.InitData?.Trim() ?? "";
        if (initData.Length == 0 || initData.Length > 4096)
            return BadRequest(new { detail = "initData is required" });
        var (status, payload) = await _hub.RouteRawAsync("telegram", "api/webapp/verify", HttpMethod.Post,
            new { init_data = initData }, timeoutSeconds: 10, ct: ct);
        var ok = status < 400 && payload.ValueKind == System.Text.Json.JsonValueKind.Object
                 && payload.TryGetProperty("ok", out var okEl) && okEl.ValueKind == System.Text.Json.JsonValueKind.True;
        if (!ok)
        {
            _logger.LogWarning("event=webui_miniapp_login_refused status={Status} ip={Ip}", status,
                HttpContext.Connection.RemoteIpAddress);
            return Unauthorized(new { detail = status >= 500 ? "Telegram not reachable" : "Not allowed" });
        }
        var token = _tokenManager.IssueMiniAppSession();
        _logger.LogInformation("event=webui_miniapp_login_success");
        return Ok(new TelegramLoginResponse("ok", token, (int)(TokenManager.MiniAppSessionHours * 3600)));
    }

    [HttpGet("status")]
    public IActionResult Status()
    {
        return Ok(_tokenManager.GetTokenStatus());
    }
}
