namespace Hestia.WebUI.Controllers;

using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Mvc;
using Hestia.WebUI.Services;

/// <summary>
/// Public door of Hestia's OAuth 2.1 server for the AIs that only speak OAuth (claude.ai web/mobile custom
/// connectors, ChatGPT). Like <c>/mcp</c> it is not under /api/webui (no WebUI login): metadata, registration, token
/// and revoke go as they are through Hub to Hestia-MCP, with the public address this request came in on in
/// <c>X-Hestia-Public-Base</c> (issuer, metadata URLs). <c>/oauth/authorize</c> never issues a code here: it parks the
/// request on Hestia-MCP and sends the browser to the consent card on the Accessi AI page (<c>/p/mcp/accessi?oauth=…</c>),
/// which sits behind the normal WebUI login. SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §B3.
/// </summary>
[ApiController]
public class OAuthDoorController : ControllerBase
{
    private const int MaxBodyBytes = 64_000;
    private static readonly Regex HostRe = new(@"^[A-Za-z0-9.\-]+(:\d{1,5})?$", RegexOptions.Compiled);
    private readonly HubClient _hubClient;
    private readonly ILogger<OAuthDoorController> _logger;

    public OAuthDoorController(HubClient hubClient, ILogger<OAuthDoorController> logger)
    {
        _hubClient = hubClient;
        _logger = logger;
    }

    /// <summary>https://host as the client sees it (the tunnel sets X-Forwarded-Proto); null on a strange Host.</summary>
    public static string? PublicBase(HttpRequest request)
    {
        var host = request.Host.Value ?? "";
        if (!HostRe.IsMatch(host)) return null;
        var scheme = request.Headers["X-Forwarded-Proto"].FirstOrDefault() ?? request.Scheme;
        scheme = scheme == "https" ? "https" : "http";
        return $"{scheme}://{host}";
    }

    private Dictionary<string, string> Headers(bool withAuth = false)
    {
        var headers = new Dictionary<string, string>();
        var basePublic = PublicBase(Request);
        if (basePublic is not null) headers["X-Hestia-Public-Base"] = basePublic;
        var auth = Request.Headers.Authorization.FirstOrDefault();
        if (withAuth && !string.IsNullOrEmpty(auth)) headers["Authorization"] = auth;
        return headers;
    }

    private static IActionResult Json(int status, JsonElement payload) => new ContentResult
    {
        StatusCode = status,
        ContentType = "application/json",
        Content = payload.ValueKind == JsonValueKind.Undefined ? "{}" : payload.GetRawText(),
    };

    private async Task<IActionResult> Forward(string path, HttpMethod method, object? body = null, bool withAuth = false)
    {
        var (status, payload) = await _hubClient.RouteRawAsync("mcp", path, method, body, timeoutSeconds: 15,
            ct: HttpContext.RequestAborted, headers: Headers(withAuth));
        Response.Headers.CacheControl = "no-store";
        if (status >= 400) _logger.LogInformation("event=oauth_door_refused path={Path} status={Status}", path, status);
        return Json(status, payload);
    }

    [HttpGet(".well-known/oauth-protected-resource")]
    [HttpGet(".well-known/oauth-protected-resource/mcp")]
    public Task<IActionResult> ProtectedResource() =>
        Forward(".well-known/oauth-protected-resource/mcp", HttpMethod.Get);

    [HttpGet(".well-known/oauth-authorization-server")]
    [HttpGet(".well-known/openid-configuration")]
    public Task<IActionResult> AuthorizationServer() =>
        Forward(".well-known/oauth-authorization-server", HttpMethod.Get);

    [HttpPost("oauth/register")]
    [RequestSizeLimit(MaxBodyBytes)]
    public async Task<IActionResult> Register()
    {
        JsonElement body;
        try { body = await JsonSerializer.DeserializeAsync<JsonElement>(Request.Body, cancellationToken: HttpContext.RequestAborted); }
        catch (JsonException) { return BadRequest(new { error = "invalid_client_metadata", error_description = "JSON body expected" }); }
        return await Forward("oauth/register", HttpMethod.Post, body);
    }

    [HttpPost("oauth/token")]
    [RequestSizeLimit(MaxBodyBytes)]
    public async Task<IActionResult> Token() =>
        await Forward("oauth/token", HttpMethod.Post, await FormBody(), withAuth: true);

    [HttpPost("oauth/revoke")]
    [RequestSizeLimit(MaxBodyBytes)]
    public async Task<IActionResult> Revoke() =>
        await Forward("oauth/revoke", HttpMethod.Post, await FormBody(), withAuth: true);

    /// <summary>OAuth clients post form-encoded; Hestia-MCP takes it as a flat JSON object through Hub.</summary>
    private async Task<Dictionary<string, string>> FormBody()
    {
        if (Request.HasFormContentType)
        {
            var form = await Request.ReadFormAsync(HttpContext.RequestAborted);
            return form.ToDictionary(kv => kv.Key, kv => kv.Value.ToString());
        }
        try
        {
            var json = await JsonSerializer.DeserializeAsync<Dictionary<string, JsonElement>>(Request.Body,
                cancellationToken: HttpContext.RequestAborted) ?? new();
            return json.ToDictionary(kv => kv.Key,
                kv => kv.Value.ValueKind == JsonValueKind.String ? kv.Value.GetString() ?? "" : kv.Value.GetRawText());
        }
        catch (JsonException) { return new(); }
    }

    /// <summary>Checks and parks the request on Hestia-MCP, then the browser goes to the consent card (login first).</summary>
    [HttpGet("oauth/authorize")]
    public async Task<IActionResult> Authorize()
    {
        var query = Request.Query.ToDictionary(kv => kv.Key, kv => kv.Value.ToString());
        var (status, payload) = await _hubClient.RouteRawAsync("mcp", "oauth/authorize", HttpMethod.Get, null, query,
            timeoutSeconds: 15, ct: HttpContext.RequestAborted, headers: Headers());
        string Str(string key) => payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty(key, out var v)
            && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";
        if (status < 400 && Str("status") == "consent")
            return Redirect($"/p/mcp/accessi?oauth={Uri.EscapeDataString(Str("request_id"))}");
        var redirect = Str("redirect");
        if (status < 400 && redirect.Length > 0)
            return Redirect(redirect);   // the client's registered redirect_uri, checked by Hestia-MCP
        _logger.LogInformation("event=oauth_door_authorize_refused status={Status} error={Error}", status, Str("error"));
        var message = System.Net.WebUtility.HtmlEncode(Str("error_description") is { Length: > 0 } d ? d : "Hestia non raggiungibile");
        return new ContentResult
        {
            StatusCode = status >= 400 ? status : 400,
            ContentType = "text/html; charset=utf-8",
            Content = $"<!doctype html><meta charset=utf-8><title>Hestia</title><body style=\"font-family:sans-serif;padding:24px\">" +
                      $"<h1>Collegamento non riuscito</h1><p>{message}</p><p>Riprova dall'app che stai collegando.</p></body>",
        };
    }
}
