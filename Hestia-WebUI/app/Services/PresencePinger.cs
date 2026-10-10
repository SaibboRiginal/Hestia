namespace Hestia.WebUI.Services;

/// <summary>
/// WebUI → assistant presence (Chronos, SPEC docs/work/2026-10-10-assistant-presence).
/// Every user action (non-GET call on /api/webui/*) counts as an interaction: debounced to one
/// ping per minute, sent in background so it never slows the request. Page views don't count.
/// </summary>
public class PresencePinger
{
    private static readonly TimeSpan Debounce = TimeSpan.FromSeconds(60);
    private readonly IServiceScopeFactory _scopes;
    private readonly ILogger<PresencePinger> _logger;
    private long _lastTicks;

    public PresencePinger(IServiceScopeFactory scopes, ILogger<PresencePinger> logger)
    {
        _scopes = scopes;
        _logger = logger;
    }

    public void Touch(string kind = "ui")
    {
        var now = DateTime.UtcNow.Ticks;
        var last = Interlocked.Read(ref _lastTicks);
        if (now - last < Debounce.Ticks || Interlocked.CompareExchange(ref _lastTicks, now, last) != last)
            return;
        _ = Task.Run(async () =>
        {
            try
            {
                using var scope = _scopes.CreateScope();
                var hub = scope.ServiceProvider.GetRequiredService<HubClient>();
                var (status, _) = await hub.RouteRawAsync("chronos", "/api/presence/ping", HttpMethod.Post,
                    new { client = "webui", kind }, timeoutSeconds: 5);
                if (status >= 400)
                    _logger.LogWarning("[🔄] event=presence_ping_failed status={Status}", status);
            }
            catch (Exception ex)
            {
                _logger.LogWarning("[🔄] event=presence_ping_failed error={Error}", ex.Message);
            }
        });
    }
}
