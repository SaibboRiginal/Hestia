namespace Hestia.WebUI.Services;

using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Extensions.Options;
using Hestia.WebUI.Models;

/// <summary>
/// Manages WebUI access tokens with single-active-token policy.
/// Tokens are generated via Telegram /webui_token and validated on every request.
/// </summary>
public class TokenManager
{
    private readonly ILogger<TokenManager> _logger;
    // Hash salt persisted next to the token state. It used to be WebUI:SecretKey, which is
    // random at every start unless configured: every restart silently invalidated the token.
    private string _salt = "";
    private string? _activeTokenHash;
    private DateTime _tokenExpiresAt = DateTime.MinValue;
    private DateTime _tokenCreatedAt = DateTime.MinValue;
    private readonly object _lock = new();

    private static readonly string StateFile =
        Environment.GetEnvironmentVariable("WEBUI_TOKEN_STATE_FILE") ?? "/app/data/token_state.json";

    public TokenManager(IOptions<WebUIOptions> options, ILogger<TokenManager> logger)
    {
        _logger = logger;
        LoadState();
        if (string.IsNullOrEmpty(_salt))
        {
            _salt = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(32));
            _activeTokenHash = null;   // a hash made with an unknown salt can never validate
            SaveState();
        }
    }

    private void LoadState()
    {
        try
        {
            if (!File.Exists(StateFile)) return;
            var json = File.ReadAllText(StateFile);
            var state = JsonSerializer.Deserialize<TokenState>(json);
            _salt = state?.Salt ?? "";
            if (state?.Hash is not null && !string.IsNullOrEmpty(_salt))
            {
                _activeTokenHash = state.Hash;
                _tokenCreatedAt = state.CreatedAt;
                _tokenExpiresAt = state.ExpiresAt;
                _logger.LogInformation("event=token_loaded_from_file expires={Exp}", _tokenExpiresAt);
            }
        }
        catch (Exception ex) { _logger.LogWarning(ex, "event=token_load_file_failed"); }
    }

    private void SaveState()
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(StateFile)!);
            var state = new TokenState
            {
                Hash = _activeTokenHash,
                Salt = _salt,
                CreatedAt = _tokenCreatedAt,
                ExpiresAt = _tokenExpiresAt,
            };
            File.WriteAllText(StateFile, JsonSerializer.Serialize(state));
        }
        catch (Exception ex) { _logger.LogWarning(ex, "event=token_save_file_failed"); }
    }

    private record TokenState
    {
        public string? Hash { get; init; }
        public string? Salt { get; init; }
        public DateTime CreatedAt { get; init; }
        public DateTime ExpiresAt { get; init; }
    }

    /// <summary>Generate a new secure random token (64 hex chars = 256 bits).</summary>
    public string GenerateToken()
    {
        var bytes = RandomNumberGenerator.GetBytes(32);
        return Convert.ToHexStringLower(bytes);
    }

    /// <summary>Constant-time comparable hash of a token.</summary>
    private string HashToken(string token)
    {
        var input = System.Text.Encoding.UTF8.GetBytes(token + _salt);
        var hash = SHA256.HashData(input);
        return Convert.ToHexStringLower(hash);
    }

    /// <summary>Validate a token against the active token.</summary>
    public bool ValidateToken(string token)
    {
        if (string.IsNullOrEmpty(token) || token.Length < 32)
            return false;

        lock (_lock)
        {
            if (_activeTokenHash is null)
                return false;

            if (_tokenExpiresAt > DateTime.MinValue && DateTime.UtcNow > _tokenExpiresAt)
                return false;

            var candidateHash = HashToken(token);
            // Constant-time comparison
            return CryptographicOperations.FixedTimeEquals(
                System.Text.Encoding.UTF8.GetBytes(candidateHash),
                System.Text.Encoding.UTF8.GetBytes(_activeTokenHash)
            );
        }
    }

    /// <summary>Set the active token, invalidating any previous one.</summary>
    public void SetActiveToken(string token, double? lifetimeHours = null)
    {
        var lifetime = lifetimeHours ?? 72;
        lock (_lock)
        {
            _activeTokenHash = HashToken(token);
            _tokenCreatedAt = DateTime.UtcNow;
            _tokenExpiresAt = _tokenCreatedAt.AddHours(lifetime);
        }
        SaveState();
        _logger.LogInformation(
            "event=webui_token_activated expires_at={ExpiresAt} lifetime_hours={Lifetime}",
            _tokenExpiresAt, lifetime);
    }

    /// <summary>Immediately invalidate the current token.</summary>
    public void RevokeToken()
    {
        lock (_lock)
        {
            _activeTokenHash = null;
            _tokenExpiresAt = DateTime.MinValue;
            _tokenCreatedAt = DateTime.MinValue;
        }
        SaveState();
        _logger.LogInformation("event=webui_token_revoked");
    }

    // Token state (hash + salt + expiry) lives only in StateFile on the hestia_webui_data
    // volume, so it survives restarts. It is never written to Archive memory: the clear
    // token stored there was readable by Oracle's memory tools.

    /// <summary>Return current token status.</summary>
    public TokenStatusResponse GetTokenStatus()
    {
        lock (_lock)
        {
            var now = DateTime.UtcNow;
            var isActive = _activeTokenHash != null
                && (_tokenExpiresAt == DateTime.MinValue || now < _tokenExpiresAt);
            var remaining = _tokenExpiresAt > now
                ? (_tokenExpiresAt - now).TotalSeconds
                : 0;

            return new TokenStatusResponse(
                Active: isActive,
                CreatedAt: _tokenCreatedAt > DateTime.MinValue ? _tokenCreatedAt : null,
                ExpiresAt: _tokenExpiresAt > DateTime.MinValue ? _tokenExpiresAt : null,
                RemainingSeconds: (int)remaining,
                RemainingHours: Math.Round(remaining / 3600.0, 1)
            );
        }
    }
}
