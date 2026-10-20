namespace Hestia.WebUI.Services;

using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.SignalR;
using Hestia.WebUI.Hubs;

/// <summary>
/// Chat messages written while Oracle is offline (SPEC docs/work/2026-10-19-oracle-offline §3).
/// A message Oracle did not accept is stored in Archive (<c>/api/chat-queue</c>, client <c>webui</c>); when the
/// Oracle is back Chronos calls <c>POST /api/chat-queue/drain</c> (capability <c>chat_queue_drain</c>), and the same
/// drain runs at startup. The backend replays each message to Oracle (no browser needed: Oracle saves the history)
/// and pushes the answer to open tabs as <c>queued_answer</c>.
/// </summary>
public class ChatQueueService
{
    public const string Client = "webui";
    public const string QueuedText = "⏳ Non posso rispondere adesso: messaggio in coda, ti rispondo appena possibile.";

    private readonly IServiceScopeFactory _scopes;
    private readonly IHubContext<ChatHub> _browsers;
    private readonly ILogger<ChatQueueService> _logger;
    private readonly SemaphoreSlim _drainLock = new(1, 1);

    public ChatQueueService(IServiceScopeFactory scopes, IHubContext<ChatHub> browsers, ILogger<ChatQueueService> logger)
    {
        _scopes = scopes;
        _browsers = browsers;
        _logger = logger;
    }

    /// <summary>Store a message; null when Archive is unreachable too (the caller shows the error).</summary>
    public async Task<JsonElement?> EnqueueAsync(HubClient hub, string sessionId, string text, string clientInstructions,
        string mode, string model, string error)
    {
        var (status, payload) = await hub.RouteRawAsync("archive", "/api/chat-queue", HttpMethod.Post, new
        {
            client = Client, session_id = sessionId, text,
            meta = new { client_instructions = clientInstructions, mode, model, error = Trim(error, 300) },
        }, timeoutSeconds: 8);
        if (status >= 400)
        {
            _logger.LogWarning("[🔄] event=chat_queue_enqueue_failed status={Status}", status);
            return null;
        }
        _logger.LogInformation("[🔄] event=chat_queued id={Id} position={Pos}",
            payload.TryGetProperty("id", out var id) ? id.ToString() : "?",
            payload.TryGetProperty("position", out var pos) ? pos.ToString() : "?");
        return payload;
    }

    /// <summary>Start a drain in the background; false when one is already running.</summary>
    public bool DrainInBackground(string reason)
    {
        if (_drainLock.CurrentCount == 0) return false;
        _ = Task.Run(() => DrainAsync(reason));
        return true;
    }

    /// <summary>Answer queued messages oldest first; stop at the first Oracle failure (still offline).</summary>
    public async Task<int> DrainAsync(string reason)
    {
        if (!await _drainLock.WaitAsync(0)) return 0;
        var answered = 0;
        try
        {
            using var scope = _scopes.CreateScope();
            var hub = scope.ServiceProvider.GetRequiredService<HubClient>();
            var oracle = scope.ServiceProvider.GetRequiredService<OracleStreamService>();
            var (status, payload) = await hub.RouteRawAsync("archive", "/api/chat-queue", HttpMethod.Get,
                query: new Dictionary<string, string> { ["client"] = Client, ["state"] = "queued" }, timeoutSeconds: 8);
            if (status >= 400 || !payload.TryGetProperty("items", out var items) || items.GetArrayLength() == 0)
                return 0;
            _logger.LogInformation("event=chat_queue_drain_start items={N} reason={Reason}", items.GetArrayLength(), reason);
            foreach (var item in items.EnumerateArray())
            {
                var id = item.GetProperty("id").GetInt32();
                var (claimStatus, _) = await hub.RouteRawAsync("archive", $"/api/chat-queue/{id}/claim", HttpMethod.Post,
                    timeoutSeconds: 8);
                if (claimStatus >= 400) continue;   // another drain holds it
                var (ok, detail) = await AnswerAsync(oracle, item);
                await hub.RouteRawAsync("archive", $"/api/chat-queue/{id}/done", HttpMethod.Post,
                    new { ok, detail = Trim(detail, 400) }, timeoutSeconds: 8);
                if (!ok) break;
                answered++;
            }
            _logger.LogInformation("event=chat_queue_drain_done answered={N}", answered);
            return answered;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[🔄] event=chat_queue_drain_failed");
            return answered;
        }
        finally
        {
            _drainLock.Release();
        }
    }

    private async Task<(bool Ok, string Detail)> AnswerAsync(OracleStreamService oracle, JsonElement item)
    {
        var id = item.GetProperty("id").GetInt32();
        var sessionId = item.GetProperty("session_id").GetString() ?? "";
        var text = item.GetProperty("text").GetString() ?? "";
        var meta = item.TryGetProperty("meta", out var m) && m.ValueKind == JsonValueKind.Object ? m : default;
        string Meta(string key) => meta.ValueKind == JsonValueKind.Object && meta.TryGetProperty(key, out var v)
            ? v.GetString() ?? "" : "";
        var when = item.TryGetProperty("created_at", out var c) && DateTimeOffset.TryParse(c.GetString(), out var at)
            ? at.ToLocalTime().ToString("dd/MM HH:mm") : "";
        var instructions = Meta("client_instructions") +
            $"\nNota: questo messaggio è stato scritto alle {when} mentre eri offline; rispondi ora tenendo conto del tempo passato.";

        var reply = new StringBuilder();
        string? final = null;
        await foreach (var evt in oracle.StreamChatAsync(text, sessionId, Meta("mode"),
                           string.IsNullOrEmpty(Meta("model")) ? "generic" : Meta("model"), instructions))
        {
            switch (evt.Type)
            {
                case OracleStreamService.UnavailableType:
                    return (false, evt.Content ?? "oracle unavailable");
                case "error":
                    return (false, evt.Content ?? "error");
                case "token":
                    reply.Append(evt.Text ?? evt.Content);
                    break;
                case "final":
                    final = evt.Reply;
                    break;
            }
        }
        var answer = final ?? reply.ToString();
        await _browsers.Clients.All.SendAsync("ReceiveEvent", new
        {
            type = "queued_answer", queue_id = id, session_id = sessionId, message = text, reply = answer,
        });
        return (true, "");
    }

    private static string Trim(string? value, int max) =>
        string.IsNullOrEmpty(value) ? "" : value.Length <= max ? value : value[..max];
}
