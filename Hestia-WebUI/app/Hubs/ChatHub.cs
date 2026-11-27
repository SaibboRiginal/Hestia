namespace Hestia.WebUI.Hubs;

using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.AspNetCore.SignalR;
using Hestia.WebUI.Models;
using Hestia.WebUI.Services;

/// <summary>
/// SignalR Hub for chat streaming. Bridges browser WebSocket messages
/// to Oracle NDJSON stream and back as typed JSON events.
///
/// Protocol (browser → server):
///   {"type":"chat","message":"...","session_id":"...","mode":"auto|quick|thinking|cot|","model":"generic","spoken":false}
///   {"type":"cancel","session_id":"..."}   «Stop»: the only thing that stops an answer
///   {"type":"attach","session_id":"..."}   page opened again / reconnected: follow the answer still running
///   {"type":"detach"}   stop following the answer here (another conversation opened); it goes on and is saved
///   {"type":"steer","message":"...","session_id":"...","id":"..."}   «Add now» while the answer runs
///   {"type":"retry"}
///   {"type":"question_answer","question_id":"...","answer":"..."}
///
/// Protocol (server → browser):
///   {"type":"token","text":"..."}
///   {"type":"status","content":"..."}
///   {"type":"thinking","action":"...","content":"...","turn":N,"tool":"..."}
///   {"type":"agent","event":"start|tool|end","agent_id":"a1","module":"...","label":"...","task":"...","ok":true}
///   {"type":"signal","event":"...","data":{...}}
///   {"type":"notice","kind":"...","level":"...","icon":"...","emoji":"...","title":"...","detail":"..."}
///   {"type":"question","question_id":"...","header":"...","prompt":"..."}
///   {"type":"final","reply":"...","session_id":"...","domain":"..."}
///   {"type":"error","content":"..."}
///   {"type":"steer","id":"...","accepted":true|false}   false = no answer running: the browser sends it next
///   {"type":"queued","queue_id":N,"position":N,"content":"..."}   Oracle offline: message queued
///   {"type":"queued_answer","queue_id":N,"session_id":"...","message":"...","reply":"..."}  (to every tab)
///   {"type":"live","running":bool,"session_id":"...","user_message":"...","text":"...","turn_id":"..."}  reply to
///       attach; when running, the turn's frames follow from its start, then stream_done
///
/// The answer runs in Oracle on its own (docs/work/2026-11-27-chat-turn-survives): a connection that goes away only
/// stops READING it; the answer is finished and saved, and the page follows it again with attach.
/// </summary>
public class ChatHub : Hub
{
    private readonly TokenManager _tokenManager;
    private readonly LocalAccess _localAccess;
    private readonly SessionManager _sessionManager;
    private readonly OracleStreamService _oracleStream;
    private readonly HubClient _hubClient;
    private readonly ChatQueueService _chatQueue;
    private readonly ILogger<ChatHub> _logger;

    // What each connection is reading (cancelling it stops the reading, never the answer in Oracle)
    private static readonly ConcurrentDictionary<string, CancellationTokenSource> _activeStreams = new();
    // The conversation each connection's running answer belongs to («Stop» stops that one)
    private static readonly ConcurrentDictionary<string, string> _activeSessions = new();

    public ChatHub(
        TokenManager tokenManager,
        LocalAccess localAccess,
        SessionManager sessionManager,
        OracleStreamService oracleStream,
        HubClient hubClient,
        ChatQueueService chatQueue,
        ILogger<ChatHub> logger)
    {
        _tokenManager = tokenManager;
        _localAccess = localAccess;
        _sessionManager = sessionManager;
        _oracleStream = oracleStream;
        _hubClient = hubClient;
        _chatQueue = chatQueue;
        _logger = logger;
    }

    public override async Task OnConnectedAsync()
    {
        var httpContext = Context.GetHttpContext();
        var token = httpContext?.Request.Query["access_token"].FirstOrDefault() ?? "";

        if (!_localAccess.IsLocal(httpContext) && !_tokenManager.ValidateToken(token))
        {
            _logger.LogWarning("event=signalr_auth_failed connection={Conn}", Context.ConnectionId);
            Context.Abort();
            return;
        }

        _logger.LogInformation("event=signalr_connected connection={Conn}", Context.ConnectionId);
        await base.OnConnectedAsync();
    }

    public override async Task OnDisconnectedAsync(Exception? exception)
    {
        // The page went away: stop reading only. Oracle finishes and saves the answer; the page follows it again
        // with attach when it comes back.
        CancelStream(Context.ConnectionId);
        _logger.LogInformation("event=signalr_disconnected connection={Conn}", Context.ConnectionId);
        await base.OnDisconnectedAsync(exception);
    }

    /// <summary>Main message handler from the browser.</summary>
    public async Task SendMessage(ChatHubMessage message)
    {
        var type = message.Type?.Trim().ToLowerInvariant() ?? "";

        switch (type)
        {
            case "chat":
                await HandleChat(message);
                break;
            case "cancel":
                await StopAnswer(message);
                await Clients.Caller.SendAsync("ReceiveEvent",
                    new { type = "status", content = "Cancelled" });
                break;
            case "attach":
                await HandleAttach(message);
                break;
            case "detach":
                // Another conversation opened / new chat: stop following here; the answer ends and is saved.
                CancelStream(Context.ConnectionId);
                break;
            case "steer":
                await HandleSteer(message);
                break;
            case "retry":
                await HandleRetry();
                break;
            case "question_answer":
                await HandleQuestionAnswer(message);
                break;
            default:
                await Clients.Caller.SendAsync("ReceiveEvent",
                    new { type = "error", content = $"Unknown type: {type}" });
                break;
        }
    }

    private async Task HandleChat(ChatHubMessage message)
    {
        var userMessage = message.Message?.Trim() ?? "";
        if (string.IsNullOrEmpty(userMessage))
        {
            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "error", content = "Empty message" });
            return;
        }

        CancelStream(Context.ConnectionId);

        var sessionId = message.SessionId?.Trim();
        if (string.IsNullOrEmpty(sessionId))
            sessionId = _sessionManager.GetOrCreateSession();

        // Quick · Auto · Thinking · CoT; anything else = "" → Oracle uses oracle.chat.mode (Themis)
        var mode = (message.Mode?.Trim().ToLowerInvariant()) switch
        {
            "quick" => "quick",
            "auto" => "auto",
            "thinking" => "thinking",
            "cot" => "cot",
            _ => ""
        };
        var model = (message.Model?.Trim().ToLowerInvariant()) switch
        {
            "reasoning" => "reasoning",
            "code" => "code",
            _ => "generic"
        };

        var pageContext = message.Context?.Trim() ?? "";
        if (pageContext.Length == 0)
            _sessionManager.SetLastMessage(userMessage);   // "Regenerate" belongs to the Chat page only
        var clientInstructions = _sessionManager.BuildClientInstructions();
        if (pageContext.Length > 0)
        {
            // "Create with the assistant": the user opened the assistant from a page; act on it with tools.
            if (pageContext.Length > 2000) pageContext = pageContext[..2000];
            clientInstructions += "\nCreate panel. Page context: " + pageContext +
                "\nAct with tools (agenda_assistant_*, commands). Confirm briefly what you created/changed." +
                "\nIf no tool can do it: propose a development (forge_develop) and ask to confirm.";
            _logger.LogInformation("event=assistant_drawer_turn connection={Conn} context_len={Len}",
                Context.ConnectionId, pageContext.Length);
        }

        var cts = new CancellationTokenSource();
        _activeStreams[Context.ConnectionId] = cts;
        _activeSessions[Context.ConnectionId] = sessionId;

        try
        {
            await foreach (var evt in _oracleStream.StreamChatAsync(
                userMessage, sessionId, mode, model, clientInstructions, cts.Token,
                spoken: message.Spoken == true))
            {
                if (evt.Type == OracleStreamService.UnavailableType && pageContext.Length == 0)
                {
                    // Oracle offline: queue it, answered when Oracle is back (SPEC oracle-offline §3).
                    var queued = await _chatQueue.EnqueueAsync(_hubClient, sessionId, userMessage, clientInstructions,
                        mode, model, evt.Content ?? "");
                    if (queued is { } q)
                    {
                        await Clients.Caller.SendAsync("ReceiveEvent", new
                        {
                            type = "queued", queue_id = q.TryGetProperty("id", out var qid) ? qid.GetInt32() : 0,
                            position = q.TryGetProperty("position", out var p) ? p.GetInt32() : 1,
                            session_id = sessionId, content = ChatQueueService.QueuedText,
                        }, cts.Token);
                        break;
                    }
                    await Clients.Caller.SendAsync("ReceiveEvent",
                        new { type = "error", content = evt.Content }, cts.Token);
                    break;
                }
                if (evt.Type == OracleStreamService.UnavailableType)
                {
                    await Clients.Caller.SendAsync("ReceiveEvent",
                        new { type = "error", content = Texts.Tr("I can't answer right now: try again later.") }, cts.Token);
                    break;
                }
                await Clients.Caller.SendAsync("ReceiveEvent", evt, cts.Token);
            }

            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "stream_done" }, cts.Token);
        }
        catch (OperationCanceledException)
        {
            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "status", content = "Stream cancelled" });
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=chat_stream_error connection={Conn}", Context.ConnectionId);
            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "error", content = ex.Message });
        }
        finally
        {
            _activeStreams.TryRemove(Context.ConnectionId, out _);
        }
    }

    /// <summary>«Add now»: the text joins the answer that is running (Oracle reads it at its next step); refused
    /// when nothing runs, and the browser then sends it as the next message (dossier real-test-problems B).</summary>
    private async Task HandleSteer(ChatHubMessage message)
    {
        var text = message.Message?.Trim() ?? "";
        var sessionId = message.SessionId?.Trim() ?? "";
        var accepted = false;
        if (text.Length > 0 && sessionId.Length > 0 && _activeStreams.ContainsKey(Context.ConnectionId))
        {
            try
            {
                var (status, payload) = await _hubClient.RouteRawAsync("oracle", "/api/chat/steer", HttpMethod.Post,
                    new { session_id = sessionId, text, id = message.Id ?? "" });
                accepted = status < 400 && payload.ValueKind == JsonValueKind.Object
                    && payload.TryGetProperty("accepted", out var a) && a.ValueKind == JsonValueKind.True;
            }
            catch (Exception ex)
            {
                _logger.LogWarning("[🔄] event=chat_steer_failed connection={Conn} error={Err}",
                    Context.ConnectionId, ex.Message);
            }
        }
        await Clients.Caller.SendAsync("ReceiveEvent", new { type = "steer", id = message.Id ?? "", accepted });
    }

    private async Task HandleRetry()
    {
        var lastMessage = _sessionManager.GetLastMessage();
        if (string.IsNullOrEmpty(lastMessage))
        {
            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "error", content = "No message to retry" });
            return;
        }

        CancelStream(Context.ConnectionId);
        var sessionId = _sessionManager.GetSession();
        var clientInstructions = _sessionManager.BuildClientInstructions();

        var cts = new CancellationTokenSource();
        _activeStreams[Context.ConnectionId] = cts;
        _activeSessions[Context.ConnectionId] = sessionId;

        try
        {
            await foreach (var evt in _oracleStream.StreamChatAsync(
                lastMessage, sessionId, "", "generic", clientInstructions, cts.Token))   // mode: this chat's setting
            {
                await Clients.Caller.SendAsync("ReceiveEvent", evt, cts.Token);
            }

            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "stream_done" }, cts.Token);
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "error", content = ex.Message });
        }
        finally
        {
            _activeStreams.TryRemove(Context.ConnectionId, out _);
        }
    }

    private async Task HandleQuestionAnswer(ChatHubMessage message)
    {
        var questionId = message.QuestionId?.Trim() ?? "";
        var answer = message.Answer?.Trim() ?? "";

        if (string.IsNullOrEmpty(questionId) || string.IsNullOrEmpty(answer))
        {
            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "error", content = "question_answer requires question_id and answer" });
            return;
        }

        try
        {
            var (status, payload) = await _hubClient.RouteRawAsync("oracle", "/api/chat/question-answer", HttpMethod.Post, new
            {
                session_id = _sessionManager.GetSession(),
                question_id = questionId,
                answer = answer,
                client = "webui"
            });
            // A confirm card made by a module (e.g. Themis proposal): Oracle routed the chosen action → show the outcome.
            if (status < 400 && payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty("action", out var action)
                && action.ValueKind == JsonValueKind.Object)
            {
                var ok = action.TryGetProperty("ok", out var okEl) && okEl.ValueKind == JsonValueKind.True;
                var approved = answer is "approve" or "yes";
                await Clients.Caller.SendAsync("ReceiveEvent", new
                {
                    type = "notice",
                    kind = ok ? "action.done" : "action.failed",
                    level = ok ? (approved ? "success" : "info") : "error",
                    icon = ok ? "check" : "alert",
                    title = ok ? (approved ? Texts.Tr("Approved") : Texts.Tr("Rejected")) : Texts.Tr("Failed"),
                    detail = ok ? "" : Texts.Tr("The answer did not arrive: try again from the notifications"),
                    data = new { question_id = questionId, answer },
                });
            }
            // A question the assistant asked (ask_user): the answer goes on as the next chat turn — the browser
            // sends `message` like a typed one, so the reply streams in the chat (oracle-offline v3 A).
            else if (status < 400 && payload.ValueKind == JsonValueKind.Object
                     && payload.TryGetProperty("resume", out var resume) && resume.ValueKind == JsonValueKind.Object
                     && resume.TryGetProperty("message", out var resumeMsg))
            {
                await Clients.Caller.SendAsync("ReceiveEvent",
                    new { type = "resume", question_id = questionId, message = resumeMsg.GetString() ?? "" });
            }
            else if (status >= 400)
            {
                await Clients.Caller.SendAsync("ReceiveEvent", new
                {
                    type = "notice", kind = "action.failed", level = "warning", icon = "clock",
                    title = Texts.Tr("Question expired"), detail = Texts.Tr("This question is no longer open: write to me again"),
                    data = new { question_id = questionId },
                });
            }
            else
            {
                await Clients.Caller.SendAsync("ReceiveEvent",
                    new { type = "status", content = $"Answer sent for {questionId}" });
            }
        }
        catch (Exception ex)
        {
            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "error", content = $"Failed: {ex.Message}" });
        }
    }

    /// <summary>«Stop»: Oracle stops the answer of this conversation, then this connection stops reading it.</summary>
    private async Task StopAnswer(ChatHubMessage message)
    {
        var sessionId = message.SessionId?.Trim();
        if (string.IsNullOrEmpty(sessionId))
            _activeSessions.TryGetValue(Context.ConnectionId, out sessionId);
        if (string.IsNullOrEmpty(sessionId))
            sessionId = _sessionManager.GetSession();
        CancelStream(Context.ConnectionId);
        try
        {
            await _hubClient.RouteRawAsync("oracle", "/api/chat/stop", HttpMethod.Post, new { session_id = sessionId },
                timeoutSeconds: 8);
            _logger.LogInformation("event=chat_stop_sent connection={Conn} session={S}", Context.ConnectionId, sessionId);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("[🔄] event=chat_stop_failed connection={Conn} session={S} error={Err}",
                Context.ConnectionId, sessionId, ex.Message);
        }
    }

    /// <summary>The page is open again (reload, back from another app, reconnected): if an answer of this
    /// conversation is still running in Oracle, say so and follow it from its start until it ends.</summary>
    private async Task HandleAttach(ChatHubMessage message)
    {
        var sessionId = message.SessionId?.Trim();
        if (string.IsNullOrEmpty(sessionId))
            sessionId = _sessionManager.GetSession();
        JsonElement turn = default;
        try
        {
            var (status, payload) = await _hubClient.RouteRawAsync("oracle", "/api/chat/live", HttpMethod.Get,
                query: new Dictionary<string, string> { ["session_id"] = sessionId }, timeoutSeconds: 8);
            if (status < 400 && payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty("turn", out var t)
                && t.ValueKind == JsonValueKind.Object)
                turn = t;
        }
        catch (Exception ex)
        {
            _logger.LogWarning("[🔄] event=chat_attach_failed connection={Conn} error={Err} fallback=history_only",
                Context.ConnectionId, ex.Message);
        }
        string Str(string key) => turn.ValueKind == JsonValueKind.Object && turn.TryGetProperty(key, out var v)
            && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";
        var running = turn.ValueKind == JsonValueKind.Object && turn.TryGetProperty("running", out var r)
            && r.ValueKind == JsonValueKind.True;
        var turnId = Str("turn_id");
        await Clients.Caller.SendAsync("ReceiveEvent", new
        {
            type = "live", running, session_id = sessionId, turn_id = turnId,
            user_message = Str("user_message"), text = Str("text"),
            found = turn.ValueKind == JsonValueKind.Object,
        });
        if (!running) return;

        CancelStream(Context.ConnectionId);
        var cts = new CancellationTokenSource();
        _activeStreams[Context.ConnectionId] = cts;
        _activeSessions[Context.ConnectionId] = sessionId;
        _logger.LogInformation("event=chat_attach connection={Conn} session={S} turn={T}",
            Context.ConnectionId, sessionId, turnId);
        try
        {
            await foreach (var evt in _oracleStream.StreamLiveAsync(sessionId, 0, turnId, cts.Token))
                await Clients.Caller.SendAsync("ReceiveEvent", evt, cts.Token);
            await Clients.Caller.SendAsync("ReceiveEvent", new { type = "stream_done" }, cts.Token);
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=chat_attach_stream_error connection={Conn}", Context.ConnectionId);
        }
        finally
        {
            if (_activeStreams.TryGetValue(Context.ConnectionId, out var cur) && cur == cts)
                _activeStreams.TryRemove(Context.ConnectionId, out _);
        }
    }

    private static void CancelStream(string connectionId)
    {
        _activeSessions.TryRemove(connectionId, out _);
        if (_activeStreams.TryRemove(connectionId, out var cts))
        {
            cts.Cancel();
            cts.Dispose();
        }
    }
}
