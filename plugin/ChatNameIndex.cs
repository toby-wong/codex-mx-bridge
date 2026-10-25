using System.Text;
using System.Text.Json;

namespace Loupedeck.CodexMxPlugin;

// Read only the optional name catalog. Never open a conversation transcript.
public sealed class ChatNameIndex
{
    private const int MaxBytes = 4 * 1024 * 1024;
    private string _stamp = "";
    private volatile Dictionary<string, string> _names = new(StringComparer.Ordinal);
    public IReadOnlyDictionary<string, string> Names => _names;

    public static Dictionary<string, string> Parse(string text)
    {
        if (Encoding.UTF8.GetByteCount(text) > MaxBytes)
            throw new InvalidDataException("Chat name index exceeds 4 MiB");
        var names = new Dictionary<string, string>(StringComparer.Ordinal);
        using var lines = new StringReader(text);
        while (lines.ReadLine() is { } line)
        {
            try
            {
                using var document = JsonDocument.Parse(line);
                var entry = document.RootElement;
                if (entry.ValueKind != JsonValueKind.Object ||
                    !entry.TryGetProperty("id", out var id) || id.ValueKind != JsonValueKind.String ||
                    !entry.TryGetProperty("thread_name", out var title) || title.ValueKind != JsonValueKind.String)
                    continue;
                string key = id.GetString()!, name = title.GetString()!;
                if (string.IsNullOrWhiteSpace(key) || key.Length > 512 || key.Any(char.IsControl)) continue;
                name = new string(name.Where(c => !char.IsControl(c)).Take(80).ToArray()).Trim();
                if (name.Length > 0) names[key] = name; // A later rename supersedes an earlier entry.
                else names.Remove(key);
            }
            catch (JsonException) { } // A writer may still be appending the last line.
        }
        return names;
    }

    public bool Refresh(string path)
    {
        Dictionary<string, string> names;
        string stamp = "";
        try
        {
            var info = new FileInfo(path);
            stamp = info.Exists ? $"{info.FullName}:{info.Length}:{info.LastWriteTimeUtc.Ticks}" : "missing";
            if (stamp == _stamp) return false;
            if (info.Exists && info.Length > MaxBytes)
                throw new InvalidDataException("Chat name index exceeds 4 MiB");
            if (info.Exists)
            {
                using var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                    FileShare.ReadWrite | FileShare.Delete);
                using var bytes = new MemoryStream();
                var buffer = new byte[8192];
                int read;
                while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
                {
                    if (bytes.Length + read > MaxBytes)
                        throw new InvalidDataException("Chat name index exceeds 4 MiB");
                    bytes.Write(buffer, 0, read);
                }
                names = Parse(Encoding.UTF8.GetString(bytes.ToArray()));
            }
            else names = new(StringComparer.Ordinal);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException or ArgumentException)
        {
            names = new(StringComparer.Ordinal);
            stamp = ""; // Retry transient file errors; explicit aliases still work.
        }
        bool changed = names.Count != _names.Count || names.Any(p =>
            !_names.TryGetValue(p.Key, out var old) || old != p.Value);
        _names = names;
        _stamp = stamp;
        return changed;
    }
}
