namespace Hestia.WebUI.Hubs;

using System.Collections.Concurrent;
using Microsoft.AspNetCore.SignalR;
using Hestia.WebUI.Models;
using Hestia.WebUI.Services;

/// <summary>
/// SignalR Hub for chat streaming. Bridges browser WebSocket messages
/// to Oracle NDJSON stream and back as typed JSON events.
///
/// Protocol (browser → server):
///   {"type":"chat","message":"...","session_id":"...","mode":"auto","model":"generic"}
///   {"type":"cancel"}
///   {"type":"retry"}
///   {"type":"question_answer","question_id":"...","answer":"..."}
///
/// Protocol (server → browser):
///   {"type":"token","text":"..."}
///   {"type":"status","content":"..."}
///   {"type":"thinking","action":"...","content":"...","turn":N,"tool":"..."}
///   {"type":"signal","event":"...","data":{...}}
///   {"type":"notice","kind":"...","level":"...","icon":"...","emoji":"...","title":"...","detail":"..."}
///   {"type":"question","question_id":"...","header":"...","prompt":"..."}
///   {"type":"final","reply":"...","session_id":"...","domain":"..."}
///   {"type":"error","content":"..."}
/// </summary>
public class ChatHub : Hub
{
    private readonly TokenManager _tokenManager;
    private readonly SessionManager _sessionManager;
    private readonly OracleStreamService _oracleStream;
    private readonly HubClient _hubClient;
    private readonly ILogger<ChatHub> _logger;

    // Track active cancellation tokens per connection
    private static readonly ConcurrentDictionary<string, CancellationTokenSource> _activeStreams = new();

    public ChatHub(
        TokenManager tokenManager,
        SessionManager sessionManager,
        OracleStreamService oracleStream,
        HubClient hubClient,
        ILogger<ChatHub> logger)
    {
        _tokenManager = tokenManager;
        _sessionManager = sessionManager;
        _oracleStream = oracleStream;
        _hubClient = hubClient;
        _logger = logger;
    }

    public override async Task OnConnectedAsync()
    {
        var httpContext = Context.GetHttpContext();
        var token = httpContext?.Request.Query["access_token"].FirstOrDefault() ?? "";

        if (!_tokenManager.ValidateToken(token))
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
                CancelStream(Context.ConnectionId);
                await Clients.Caller.SendAsync("ReceiveEvent",
                    new { type = "status", content = "Cancelled" });
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

        var mode = (message.Mode?.Trim().ToLowerInvariant()) switch
        {
            "quick" => "quick",
            "thinking" => "thinking",
            _ => "auto"
        };
        var model = (message.Model?.Trim().ToLowerInvariant()) switch
        {
            "reasoning" => "reasoning",
            "code" => "code",
            _ => "generic"
        };

        var pageContext = message.Context?.Trim() ?? "";
        if (pageContext.Length == 0)
            _sessionManager.SetLastMessage(userMessage);   // "Rigenera" belongs to the Chat page only
        var clientInstructions = _sessionManager.BuildClientInstructions();
        if (pageContext.Length > 0)
        {
            // "Crea con Hestia": the user opened the assistant from a page; act on it with tools.
            if (pageContext.Length > 2000) pageContext = pageContext[..2000];
            clientInstructions += "\nPannello Crea con Hestia. Contesto pagina: " + pageContext +
                "\nAgisci con gli strumenti (agenda_assistente_*, comandi). Conferma breve cosa hai creato/modificato." +
                "\nSe nessuno strumento può farlo: proponi uno sviluppo (forge_develop) e chiedi conferma.";
            _logger.LogInformation("event=assistant_drawer_turn connection={Conn} context_len={Len}",
                Context.ConnectionId, pageContext.Length);
        }

        var cts = new CancellationTokenSource();
        _activeStreams[Context.ConnectionId] = cts;

        try
        {
            await foreach (var evt in _oracleStream.StreamChatAsync(
                userMessage, sessionId, mode, model, clientInstructions, cts.Token))
            {
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

        try
        {
            await foreach (var evt in _oracleStream.StreamChatAsync(
                lastMessage, sessionId, "auto", "generic", clientInstructions, cts.Token))
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
            await _hubClient.RoutePostAsync("oracle", "/api/chat/question-answer", new
            {
                session_id = _sessionManager.GetSession(),
                question_id = questionId,
                answer = answer,
                client = "web"
            });
            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "status", content = $"Answer sent for {questionId}" });
        }
        catch (Exception ex)
        {
            await Clients.Caller.SendAsync("ReceiveEvent",
                new { type = "error", content = $"Failed: {ex.Message}" });
        }
    }

    private static void CancelStream(string connectionId)
    {
        if (_activeStreams.TryRemove(connectionId, out var cts))
        {
            cts.Cancel();
            cts.Dispose();
        }
    }
}
