namespace Hestia.WebUI.Services;

using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.SignalR;
using Hestia.WebUI.Hubs;

/// <summary>
/// Chat messages written while Oracle is offline (SPEC docs/work/2026-10-19-oracle-offline §3).
/// A message Oracle did not accept is stored in Archive (<c>/api/chat-queue</c>, client <c>webui</c>); when the
/// Oracle is back Chronos calls <c>POST /api/chat-queue/drain</c> (capability <c>chat_queue_drain</c>), and the same
/// drain runs at startup. The backend sends each chat's messages to Oracle in one turn (no browser needed: Oracle
/// saves the history) and pushes the answer to open tabs as <c>queued_answer</c>.
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

    /// <summary>Answer queued messages chat by chat (oldest chat first); stop at the first Oracle failure.
    /// All messages of one chat go to Oracle in one turn (<c>queued</c>): the assistant decides whether to answer
    /// each, merge them, or ask which old ones still matter (oracle-offline v3 C).</summary>
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
            var chats = items.EnumerateArray()
                .GroupBy(i => i.GetProperty("session_id").GetString() ?? "")
                .OrderBy(g => g.Min(i => i.GetProperty("id").GetInt32()));
            foreach (var chat in chats)
            {
                var claimed = new List<JsonElement>();
                foreach (var item in chat.OrderBy(i => i.GetProperty("id").GetInt32()))
                {
                    var id = item.GetProperty("id").GetInt32();
                    var (claimStatus, _) = await hub.RouteRawAsync("archive", $"/api/chat-queue/{id}/claim",
                        HttpMethod.Post, timeoutSeconds: 8);
                    if (claimStatus < 400) claimed.Add(item);   // else another drain holds it
                }
                if (claimed.Count == 0) continue;
                var (ok, detail) = await AnswerAsync(oracle, chat.Key, claimed);
                foreach (var item in claimed)
                    await hub.RouteRawAsync("archive", $"/api/chat-queue/{item.GetProperty("id").GetInt32()}/done",
                        HttpMethod.Post, new { ok, detail = Trim(detail, 400) }, timeoutSeconds: 8);
                if (!ok) break;
                answered += claimed.Count;
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

    private async Task<(bool Ok, string Detail)> AnswerAsync(OracleStreamService oracle, string sessionId,
        List<JsonElement> items)
    {
        var first = items[0];
        var meta = first.TryGetProperty("meta", out var m) && m.ValueKind == JsonValueKind.Object ? m : default;
        string Meta(string key) => meta.ValueKind == JsonValueKind.Object && meta.TryGetProperty(key, out var v)
            ? v.GetString() ?? "" : "";
        var queued = items.Select(i => (object)new
        {
            text = i.GetProperty("text").GetString() ?? "",
            written_at = i.TryGetProperty("created_at", out var c) ? c.GetString() : null,
        }).ToList();
        var ids = items.Select(i => i.GetProperty("id").GetInt32()).ToArray();
        var texts = items.Select(i => i.GetProperty("text").GetString() ?? "").ToArray();

        var reply = new StringBuilder();
        string? final = null;
        await foreach (var evt in oracle.StreamChatAsync("", sessionId, Meta("mode"),
                           string.IsNullOrEmpty(Meta("model")) ? "generic" : Meta("model"),
                           Meta("client_instructions"), queued: queued))
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
                case "question":
                    // The assistant asks (e.g. which old messages to keep): open tabs show the card; a reloaded tab
                    // gets it again from Oracle's open questions.
                    await _browsers.Clients.All.SendAsync("ReceiveEvent", evt);
                    break;
            }
        }
        var answer = final ?? reply.ToString();
        await _browsers.Clients.All.SendAsync("ReceiveEvent", new
        {
            type = "queued_answer", queue_id = ids[^1], queue_ids = ids, session_id = sessionId,
            message = string.Join("\n", texts), reply = answer,
        });
        return (true, "");
    }

    private static string Trim(string? value, int max) =>
        string.IsNullOrEmpty(value) ? "" : value.Length <= max ? value : value[..max];
}
