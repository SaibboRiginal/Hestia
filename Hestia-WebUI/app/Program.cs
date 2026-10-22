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
// WebUI__SecretKey="" (compose default) must not replace the random key with an empty one.
builder.Services.PostConfigure<WebUIOptions>(o =>
{
    if (string.IsNullOrWhiteSpace(o.SecretKey))
        o.SecretKey = Convert.ToHexString(System.Security.Cryptography.RandomNumberGenerator.GetBytes(32));
});

var webuiOpts = builder.Configuration.GetSection(WebUIOptions.Section).Get<WebUIOptions>()!;
var hestiaOpts = builder.Configuration.GetSection(HestiaOptions.Section).Get<HestiaOptions>()!;

// ── Services ───────────────────────────────────────────────────────────────
builder.Services.AddSingleton<TokenManager>();
builder.Services.AddSingleton<SessionManager>();
builder.Services.AddSingleton<PublicUrlService>();
builder.Services.AddSingleton<PresencePinger>();
builder.Services.AddSingleton<WebUISettings>();
builder.Services.AddSingleton<LocalAccess>();
builder.Services.AddSingleton<PluginCatalog>();
builder.Services.AddSingleton<ChatQueueService>();
builder.Services.AddHostedService<WebUISettingsRegistrar>();

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

builder.Services.AddSignalR(opts =>
    {
        // Default is 1 invocation per client: a running chat stream blocked
        // "cancel" and question answers until the stream ended.
        opts.MaximumParallelInvocationsPerClient = 4;
    })
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
    var viaCloudflare = context.Request.Headers.ContainsKey("Cf-Connecting-Ip");
    publicUrl.TryDetectFromHost(host, scheme, viaCloudflare);
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

    // Token state is restored by TokenManager from /app/data (volume), not from Archive.

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
            // Hermes delivers every notification here (SPEC hermes-global-notifications).
            notify_endpoint = "/api/notify",
            // Chronos calls it when Oracle is back (SPEC oracle-offline): answer the queued chat messages.
            chat_queue_drain = "/api/chat-queue/drain",
            // Assistant tools: widget catalog + dashboards (client plugins SPEC §4.6), next to Themis'.
            // /api/ai/mcp: the WebUI's own module tools. /mcp is the public door for external AIs.
            mcp_endpoint = $"{hestiaOpts.ServiceBaseUrl.TrimEnd('/')}/api/ai/mcp",
            module_tool_domains = new[] { "system", "settings" },
            // Voice uses (dossier modulo-voce §5): the voice module shows them in «Motori» with chain and mode.
            voice_usecases = Hestia.WebUI.Controllers.VoiceController.UseCases,
        }
    };
    var payloadJson = JsonSerializer.Serialize(payload);
    var httpFactory = app.Services.GetRequiredService<IHttpClientFactory>();

    async Task<bool> RegisterOnHubAsync()
    {
        try
        {
            var content = new StringContent(payloadJson, System.Text.Encoding.UTF8, "application/json");
            var resp = await httpFactory.CreateClient().PostAsync($"{hestiaOpts.HubApiUrl}/registry/register", content);
            if (resp.IsSuccessStatusCode) return true;
            logger.LogWarning("event=hub_registration_failed status={Status} body={Body}", (int)resp.StatusCode, await resp.Content.ReadAsStringAsync());
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "event=hub_registration_failed_non_fatal");
        }
        return false;
    }

    if (await RegisterOnHubAsync())
        logger.LogInformation("event=registered_on_hub hub={Hub} service={Svc}", hestiaOpts.HubApiUrl, hestiaOpts.ServiceName);
    // Messages queued while Oracle was offline (and the WebUI was down too) get their answer now.
    app.Services.GetRequiredService<ChatQueueService>().DrainInBackground("startup");

    // Keepalive like the Python services: the Hub marks a service offline after 180 s without a registration
    // and forgets it on restart. The WebUI registered only once (found by the cloud test bench, 2026-10-19).
    _ = Task.Run(async () =>
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(60));
        try
        {
            while (await timer.WaitForNextTickAsync(app.Lifetime.ApplicationStopping))
                await RegisterOnHubAsync();
        }
        catch (OperationCanceledException) { /* shutting down */ }
    });
}

// ── Middleware Pipeline ────────────────────────────────────────────────────
app.UseCors();

app.Use(async (context, next) =>
{
    context.Response.Headers["X-Content-Type-Options"] = "nosniff";
    context.Response.Headers["X-Frame-Options"] = "DENY";
    context.Response.Headers["Referrer-Policy"] = "no-referrer";
    context.Response.Headers["Content-Security-Policy"] =
        // blob: = module plugin bundles (fetched with the token, imported as blob modules); https: images =
        // photos a module shows from the web (e.g. Scout listing photos). Client plugins SPEC §4.3.
        "default-src 'self'; script-src 'self' 'unsafe-inline' blob:; " +
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; " +
        "font-src 'self' https://fonts.gstatic.com; connect-src 'self' ws: wss:; " +
        "img-src 'self' data: blob: https:; frame-src 'none'; object-src 'none'";
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
    // index.html must never be cached: it names the hashed bundles, and a stale copy keeps running the
    // old app after an update (e.g. the old login flow). Hashed .js/.css stay cacheable.
    // sw.js and the plugin SDK runtime (/plugins/_sdk/) are not hashed either: always revalidated.
    var types = new Microsoft.AspNetCore.StaticFiles.FileExtensionContentTypeProvider();
    types.Mappings[".webmanifest"] = "application/manifest+json";
    var staticOpts = new StaticFileOptions
    {
        ContentTypeProvider = types,
        OnPrepareResponse = ctx =>
        {
            var name = ctx.File.Name;
            if (name.EndsWith(".html", StringComparison.OrdinalIgnoreCase) || name == "sw.js" || name.EndsWith(".webmanifest"))
                ctx.Context.Response.Headers.CacheControl = "no-cache, no-store, must-revalidate";
            else if (ctx.Context.Request.Path.StartsWithSegments("/plugins/_sdk"))
                ctx.Context.Response.Headers.CacheControl = "no-cache";
        },
    };
    app.UseDefaultFiles();
    app.UseStaticFiles(staticOpts);
    app.MapFallbackToFile("index.html", staticOpts);
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
