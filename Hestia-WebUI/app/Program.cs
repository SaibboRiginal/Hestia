using System.Text.Json;
using Hestia.WebUI.Hubs;
using Hestia.WebUI.Middleware;
using Hestia.WebUI.Services;

var builder = WebApplication.CreateBuilder(args);

// ── Configuration ──────────────────────────────────────────────────────────
builder.Services.Configure<WebUIOptions>(
    builder.Configuration.GetSection(WebUIOptions.Section));
builder.Services.Configure<HestiaOptions>(
    builder.Configuration.GetSection(HestiaOptions.Section));

var webuiOpts = builder.Configuration.GetSection(WebUIOptions.Section).Get<WebUIOptions>()!;
var hestiaOpts = builder.Configuration.GetSection(HestiaOptions.Section).Get<HestiaOptions>()!;

// ── Services ───────────────────────────────────────────────────────────────
builder.Services.AddSingleton<TokenManager>();
builder.Services.AddSingleton<SessionManager>();
builder.Services.AddSingleton<PublicUrlService>();

builder.Services.AddHttpClient<HubClient>(client =>
{
    client.Timeout = TimeSpan.FromSeconds(30);
});

// OracleStreamService is registered as a typed HttpClient so it receives
// a properly-configured HttpClient with streaming-friendly timeout.
builder.Services.AddHttpClient<OracleStreamService>(client =>
{
    client.Timeout = TimeSpan.FromMinutes(5);
});

builder.Services.AddControllers()
    .AddJsonOptions(opts =>
    {
        opts.JsonSerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;
        opts.JsonSerializerOptions.PropertyNameCaseInsensitive = true;
    });

builder.Services.AddSignalR()
    .AddJsonProtocol(opts =>
    {
        opts.PayloadSerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;
        opts.PayloadSerializerOptions.PropertyNameCaseInsensitive = true;
    });

// Swagger (serves its own docs at :19015/swagger)
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(opts =>
{
    opts.SwaggerDoc("v1", new()
    {
        Title = "Hestia WebUI",
        Version = "v1",
        Description = "Web-based chat interface for Hestia. Admin endpoints for token management."
    });
});

// ── CORS ───────────────────────────────────────────────────────────────────
builder.Services.AddCors(opts =>
{
    opts.AddDefaultPolicy(policy =>
    {
        policy.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod();
    });
    opts.AddPolicy("SignalR", policy =>
    {
        policy.SetIsOriginAllowed(_ => true)
              .AllowAnyHeader().AllowAnyMethod().AllowCredentials();
    });
});

var app = builder.Build();

// ── Swagger UI ─────────────────────────────────────────────────────────────
app.UseSwagger();
app.UseSwaggerUI(opts =>
{
    opts.SwaggerEndpoint("/swagger/v1/swagger.json", "Hestia WebUI v1");
    opts.RoutePrefix = "swagger";
});

// ── Host header auto-detection (Cloudflare tunnel public URL) ──────────────
app.Use(async (context, next) =>
{
    var publicUrl = context.RequestServices.GetRequiredService<PublicUrlService>();
    var host = context.Request.Host.Value ?? "";
    var scheme = context.Request.Headers["X-Forwarded-Proto"].FirstOrDefault()
                 ?? context.Request.Scheme;
    publicUrl.TryDetectFromHost(host, scheme);
    await next();
});

// ── Startup: Discover Oracle & Register on Hub ─────────────────────────────
using (var scope = app.Services.CreateScope())
{
    var hubClient = scope.ServiceProvider.GetRequiredService<HubClient>();
    var oracleStream = scope.ServiceProvider.GetRequiredService<OracleStreamService>();
    var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();

    // Retry Oracle discovery — Oracle must be registered in Hub before chat works
    var oracleTimeout = TimeSpan.FromSeconds(120);
    var oracleStart = DateTime.UtcNow;
    while (DateTime.UtcNow - oracleStart < oracleTimeout)
    {
        if (await oracleStream.DiscoverAsync(hubClient)) break;
        await Task.Delay(2000);
    }
    if (!oracleStream.IsReady)
        logger.LogWarning("event=oracle_discovery_timeout via=Hub");

    // Restore token state from Archive (survives container restarts)
    try
    {
        var tokenManager = scope.ServiceProvider.GetRequiredService<TokenManager>();
        await tokenManager.RestoreFromArchiveAsync(hubClient);
    }
    catch (Exception ex)
    {
        logger.LogWarning(ex, "event=token_restore_startup_failed");
    }

    try
    {
        var payload = new
        {
            name = hestiaOpts.ServiceName,
            base_url = hestiaOpts.ServiceBaseUrl,
            health_endpoint = "/health",
            service_type = hestiaOpts.ServiceType,
            service_version = hestiaOpts.ServiceVersion,
            tags = hestiaOpts.ServiceTags.Split(',').Select(t => t.Trim()).Where(t => t.Length > 0).ToList(),
            topology_tags = hestiaOpts.ServiceTopologyTags.Split(',').Select(t => t.Trim()).Where(t => t.Length > 0).ToList(),
            capabilities = new
            {
                interface_type = "web",
                swagger_endpoint = $"{hestiaOpts.ServiceBaseUrl}/swagger",
                hub_events_webhook = "/api/events/registry-changed",
            }
        };

        var httpClient = scope.ServiceProvider.GetRequiredService<IHttpClientFactory>().CreateClient();
        var content = new StringContent(JsonSerializer.Serialize(payload), System.Text.Encoding.UTF8, "application/json");
        var resp = await httpClient.PostAsync($"{hestiaOpts.HubApiUrl}/registry/register", content);

        if (resp.IsSuccessStatusCode)
            logger.LogInformation("event=registered_on_hub hub={Hub} service={Svc}", hestiaOpts.HubApiUrl, hestiaOpts.ServiceName);
        else
            logger.LogWarning("event=hub_registration_failed status={Status} body={Body}", (int)resp.StatusCode, await resp.Content.ReadAsStringAsync());
    }
    catch (Exception ex)
    {
        logger.LogWarning(ex, "event=hub_registration_failed_non_fatal");
    }
}

// ── Middleware Pipeline ────────────────────────────────────────────────────
app.UseCors();

app.Use(async (context, next) =>
{
    context.Response.Headers["X-Content-Type-Options"] = "nosniff";
    context.Response.Headers["X-Frame-Options"] = "DENY";
    context.Response.Headers["Referrer-Policy"] = "no-referrer";
    context.Response.Headers["Content-Security-Policy"] =
        "default-src 'self'; script-src 'self' 'unsafe-inline'; " +
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; " +
        "font-src 'self' https://fonts.gstatic.com; connect-src 'self' ws: wss:; " +
        "img-src 'self' data: blob:; frame-src 'none'; object-src 'none'";
    await next();
});

app.UseWebUITokenAuth();
app.MapControllers();

// ── SignalR Hub ────────────────────────────────────────────────────────────
app.MapHub<ChatHub>("/hubs/chat").RequireCors("SignalR");

// ── Health Endpoint ────────────────────────────────────────────────────────
app.MapGet("/health", () => new
{
    status = "ok",
    service = hestiaOpts.ServiceName,
    version = hestiaOpts.ServiceVersion,
    service_type = hestiaOpts.ServiceType,
    tags = hestiaOpts.ServiceTags.Split(',').Select(t => t.Trim()).Where(t => t.Length > 0).ToList(),
});

// ── Static Files (Angular build output) ────────────────────────────────────
var staticDir = Path.Combine(app.Environment.ContentRootPath, webuiOpts.StaticDir);
if (Directory.Exists(staticDir))
{
    app.UseDefaultFiles();
    app.UseStaticFiles();
    app.MapFallbackToFile("index.html");
}

app.MapGet("/api/logs/level", () => new { level = "Information" });
app.MapPost("/api/logs/level", (LevelRequest req) =>
{
    app.Logger.LogInformation("event=log_level_change_requested level={Level}", req.Level);
    return Results.Ok(new { status = "ok", level = req.Level });
});

var port = webuiOpts.Port;
app.Urls.Add($"http://0.0.0.0:{port}");

app.Logger.LogInformation("event=webui_startup service={Svc} version={Ver} port={Port}", hestiaOpts.ServiceName, hestiaOpts.ServiceVersion, port);

app.Run();

record LevelRequest(string Level);
