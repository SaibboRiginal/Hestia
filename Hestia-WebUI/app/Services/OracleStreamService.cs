namespace Hestia.WebUI.Services;

using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;
using Hestia.WebUI.Models;

/// <summary>
/// Oracle NDJSON streaming client. ALL calls route through Hub.
/// Follows Hestia architecture rule: every service uses exactly HUB_API_URL.
/// </summary>
public class OracleStreamService
{
    private readonly HttpClient _http;
    private readonly string _hubUrl;
    private readonly ILogger<OracleStreamService> _logger;
    private volatile bool _oracleReady;

    public static readonly HashSet<string> AcceptedMimes = new(StringComparer.OrdinalIgnoreCase)
    {
        "image/jpeg", "image/jpg", "image/png", "image/webp",
        "image/gif", "image/heic", "image/heif", "image/bmp", "image/tiff",
        "application/pdf",
        "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
        "audio/ogg", "audio/vorbis", "audio/flac", "audio/aac",
        "audio/x-aac", "audio/m4a", "audio/mp4",
        "video/mp4", "video/mpeg", "video/webm", "video/ogg",
        "video/quicktime", "video/x-msvideo",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain", "text/csv", "text/markdown", "text/html",
        "application/json", "application/xml", "text/xml",
        "application/x-yaml", "application/yaml",
    };

    public OracleStreamService(HttpClient http, IOptions<HestiaOptions> opts, ILogger<OracleStreamService> logger)
    {
        _http = http;
        _hubUrl = opts.Value.HubApiUrl.TrimEnd('/');
        _logger = logger;
    }

    public bool IsReady => _oracleReady;

    public async Task<bool> DiscoverAsync(HubClient hub)
    {
        try
        {
            var svc = await hub.GetServiceAsync("oracle");
            _oracleReady = svc is not null;
            if (_oracleReady)
                _logger.LogInformation("event=oracle_ready_via_hub");
            else
                _logger.LogWarning("event=oracle_not_found_in_hub");
            return _oracleReady;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=oracle_discovery_failed");
            return false;
        }
    }

    public IAsyncEnumerable<OracleEvent> StreamChatAsync(
        string message, string sessionId,
        string mode = "auto", string model = "generic",
        string? clientInstructions = null,
        CancellationToken ct = default)
    {
        var body = new Dictionary<string, object>
        {
            ["message"] = message, ["session_id"] = sessionId,
            ["mode"] = mode, ["model"] = model,
            ["save_history"] = true, ["force_notification_compiler"] = false,
        };
        if (!string.IsNullOrWhiteSpace(clientInstructions))
            body["client_instructions"] = clientInstructions;

        _logger.LogInformation("event=oracle_stream_start session={S} mode={M} model={D} msg_len={L}",
            sessionId, mode, model, message.Length);

        var envelope = new
        {
            method = "POST",
            body = (object)body,
            timeout_seconds = 180.0,
            stream = true,
        };

        return StreamViaHub("oracle", "/api/chat", envelope, ct);
    }

    /// <summary>
    /// Stream a document analysis request through Hub routing to Oracle.
    /// NDJSON like chat, via Oracle's /api/chat/document/json (base64 body).
    /// </summary>
    public IAsyncEnumerable<OracleEvent> StreamDocumentAsync(
        byte[] fileBytes, string filename, string mimeType,
        string message, string sessionId,
        string? clientInstructions = null,
        CancellationToken ct = default)
    {
        var base64Content = Convert.ToBase64String(fileBytes);

        var body = new Dictionary<string, object>
        {
            ["message"] = message,
            ["session_id"] = sessionId,
            ["filename"] = filename,
            ["mime_type"] = mimeType,
            ["content_base64"] = base64Content,
        };
        if (!string.IsNullOrWhiteSpace(clientInstructions))
            body["client_instructions"] = clientInstructions;

        _logger.LogInformation("event=oracle_document_stream_start session={S} file={F} mime={M} size={B}",
            sessionId, filename, mimeType, fileBytes.Length);

        var envelope = new
        {
            method = "POST",
            body = (object)body,
            timeout_seconds = 300.0,
            stream = true,
        };

        // JSON twin of Oracle's multipart /api/chat/document (Hub envelopes carry JSON only;
        // a "document" field on /api/chat was silently ignored).
        return StreamViaHub("oracle", "/api/chat/document/json", envelope, ct);
    }

    private async IAsyncEnumerable<OracleEvent> StreamViaHub(
        string service, string path, object envelope,
        [EnumeratorCancellation] CancellationToken ct)
    {
        var url = $"{_hubUrl}/route/{service}/{path.TrimStart('/')}";
        var content = new StringContent(
            JsonSerializer.Serialize(envelope), Encoding.UTF8, "application/json");

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromMinutes(4));

        // ── Connect (yield not allowed inside catch, so capture the fatal event) ─
        HttpResponseMessage? resp = null;
        OracleEvent? fatalEvent = null;
        try
        {
            var req = new HttpRequestMessage(HttpMethod.Post, url) { Content = content };
            resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, cts.Token);
            resp.EnsureSuccessStatusCode();
        }
        catch (OperationCanceledException)
        {
            _logger.LogInformation("event=hub_stream_cancelled");
            fatalEvent = new OracleEvent("status", Content: "Stream cancelled");
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "event=hub_stream_error url={Url}", url);
            fatalEvent = new OracleEvent("error", Content: ex.Message);
        }

        if (fatalEvent is not null)
        {
            yield return fatalEvent;
            yield break;
        }

        // ── Stream NDJSON lines ───────────────────────────────────────────
        _logger.LogDebug("event=hub_stream_connected url={Url}", url);

        using var s = await resp!.Content.ReadAsStreamAsync(cts.Token);
        using var r = new StreamReader(s);

        var lineCount = 0;
        while (!r.EndOfStream && !ct.IsCancellationRequested)
        {
            var line = await r.ReadLineAsync(ct);
            if (string.IsNullOrWhiteSpace(line)) continue;

            OracleEvent? evt = null;
            try
            {
                evt = JsonSerializer.Deserialize<OracleEvent>(line);
            }
            catch (JsonException ex)
            {
                _logger.LogWarning(ex, "event=ndjson_parse_error line_len={Len} line_preview={Preview}",
                    line.Length, line[..Math.Min(line.Length, 200)]);
                // Skip unparseable lines but keep streaming — one bad frame
                // should not kill the entire response.
                continue;
            }

            if (evt is not null)
            {
                lineCount++;
                yield return evt;
            }
        }

        _logger.LogInformation("event=hub_stream_done lines={Count}", lineCount);
    }
}
