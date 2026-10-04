namespace Hestia.WebUI.Middleware;

using Hestia.WebUI.Services;

/// <summary>
/// Middleware that validates the WebUI access token on EVERY request.
/// Token is extracted from X-Access-Token header or ?token= query param.
/// Applied to all /api/webui/* paths. WebSocket auth is handled in the Hub.
/// </summary>
public class TokenAuthMiddleware
{
    private readonly RequestDelegate _next;

    public TokenAuthMiddleware(RequestDelegate next)
    {
        _next = next;
    }

    public async Task InvokeAsync(HttpContext context, TokenManager tokenManager)
    {
        // Skip paths that don't require auth
        var path = context.Request.Path.Value ?? "";

        if (path == "/health" || path == "/api/logs/level" || path.StartsWith("/api/logs"))
        {
            await _next(context);
            return;
        }

        // Only protect /api/webui/ paths
        if (!path.StartsWith("/api/webui/"))
        {
            await _next(context);
            return;
        }

        // Allow login endpoint without token
        if (path == "/api/webui/auth/login" && context.Request.Method == "POST")
        {
            await _next(context);
            return;
        }

        // Commands are read-only metadata — no auth needed
        if (path == "/api/webui/commands")
        {
            await _next(context);
            return;
        }

        // Admin API is internal-network only — called by Telegram, not the browser
        if (path.StartsWith("/api/webui/admin/"))
        {
            await _next(context);
            return;
        }

        // Read-only agenda ICS feed for phone calendars: dedicated key (WEBUI_ICS_KEY, >= 16 chars).
        if (path == "/api/webui/agenda/feed.ics" && context.Request.Method == "GET")
        {
            var icsKey = Environment.GetEnvironmentVariable("WEBUI_ICS_KEY") ?? "";
            var given = context.Request.Query["key"].FirstOrDefault() ?? "";
            if (icsKey.Length >= 16 && given.Length == icsKey.Length &&
                System.Security.Cryptography.CryptographicOperations.FixedTimeEquals(
                    System.Text.Encoding.UTF8.GetBytes(given), System.Text.Encoding.UTF8.GetBytes(icsKey)))
            {
                await _next(context);
                return;
            }
        }

        // Extract token from header or query string
        var token = context.Request.Headers["X-Access-Token"].FirstOrDefault()
                    ?? context.Request.Query["token"].FirstOrDefault()
                    ?? "";

        if (!tokenManager.ValidateToken(token))
        {
            context.Response.StatusCode = 401;
            context.Response.ContentType = "application/json";
            await context.Response.WriteAsync(
                """{"detail":"Invalid or missing access token"}""");
            return;
        }

        await _next(context);
    }
}

/// <summary>Extension method to register the middleware.</summary>
public static class TokenAuthMiddlewareExtensions
{
    public static IApplicationBuilder UseWebUITokenAuth(this IApplicationBuilder builder)
    {
        return builder.UseMiddleware<TokenAuthMiddleware>();
    }
}
