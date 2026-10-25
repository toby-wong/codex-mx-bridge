using System.Buffers.Binary;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Loupedeck.CodexMxPlugin;

public sealed class DisplayOptions
{
    public const int MaxBytes = 65536;
    public int SchemaVersion { get; set; }
    public string Mode { get; set; } = "text";
    public string Pet { get; set; } = "";
    public int Fps { get; set; } = 4;
    public bool Animate { get; set; } = true;
    public bool ShowName { get; set; } = true;
    public bool ShowLocation { get; set; } = true;
    public bool ShowClient { get; set; } = true;
    public bool ShowStatus { get; set; } = true;
    public bool UseChatNames { get; set; } = true;
    public string ChatView { get; set; } = "paged";
    public Dictionary<string, string> NameOverrides { get; set; } = new();
    public static DisplayOptions Parse(string text)
    {
        if (System.Text.Encoding.UTF8.GetByteCount(text) > MaxBytes)
            throw new JsonException("display.json exceeds 64 KiB");
        var o = JsonSerializer.Deserialize<DisplayOptions>(text, ViewModel.Json) ?? throw new JsonException("Missing display config");
        if (o.SchemaVersion != 1 || o.Mode is not ("text" or "pet") || o.Pet is null ||
            o.Fps is < 1 or > 8 || (o.Pet.Length > 0 && !Regex.IsMatch(o.Pet, @"\A[a-zA-Z0-9_-]{1,48}/[a-f0-9]{16}\z")) ||
            (o.Mode == "pet" && o.Pet.Length == 0) ||
            o.ChatView is not ("paged" or "recent" or "recent_open" or "newest"))
            throw new JsonException("Invalid display mode, pet revision or frame rate");
        if (o.NameOverrides is null || o.NameOverrides.Count > 64 ||
            o.NameOverrides.Any(p => string.IsNullOrWhiteSpace(p.Key) || p.Key.Length > 700 ||
                p.Key.Any(char.IsControl) || string.IsNullOrWhiteSpace(p.Value) ||
                p.Value.Length > 80 || p.Value.Any(char.IsControl)))
            throw new JsonException("Invalid chat name overrides");
        return o;
    }
}

public sealed record ButtonLabels(string Header, string Footer)
{
    public string Text => string.Join("\n", new[] { Header, Footer }.Where(s => s.Length > 0));
}

public sealed class PetManifest
{
    public int SchemaVersion { get; set; }
    public string Name { get; set; } = "";
    public int FrameWidth { get; set; }
    public int FrameHeight { get; set; }
    public Dictionary<string, string[]> Animations { get; set; } = new();
    public static PetManifest Parse(string text)
    {
        var p = JsonSerializer.Deserialize<PetManifest>(text, ViewModel.Json) ?? throw new JsonException("Missing pet manifest");
        if (p.SchemaVersion != 1 || p.FrameWidth is < 1 or > 512 || p.FrameHeight is < 1 or > 512 ||
            p.Animations is null || p.Animations.Count > 16 ||
            new[] { "idle", "running", "waiting", "review", "failed" }.Any(k => !p.Animations.ContainsKey(k)))
            throw new JsonException("Invalid pet manifest geometry or animations");
        int total = 0;
        foreach (var (name, frames) in p.Animations)
        {
            if (!Regex.IsMatch(name, @"\A[a-z_]{1,32}\z") || frames is null || frames.Length is < 1 or > 32 ||
                frames.Any(f => f is null || !Regex.IsMatch(f, @"\A[a-z_]{1,32}-[0-9]{1,2}\.png\z")))
                throw new JsonException("Unsafe or invalid pet frame name");
            total += frames.Length;
        }
        if (total > 128) throw new JsonException("Too many pet frames");
        return p;
    }
}

public static class DisplayPlan
{
    public static ButtonLabels Labels(Tile tile, DisplayOptions options,
        IReadOnlyDictionary<string, string>? chatNames = null)
    {
        // Keep install/read errors visible even when ordinary labels are hidden.
        if (tile.Host == "bridge") return new($"{tile.Header}\n{tile.Name}", tile.Status);
        var lines = new List<string>();
        var source = new List<string>();
        if (options.ShowClient)
            source.Add(tile.Client switch { "claude" => "Claude", "kiro" => "Kiro", _ => "Codex" });
        if (options.ShowLocation)
            source.Add(tile.Host == "local" ? "local" : $"remote: {tile.Host}");
        if (source.Count > 0) lines.Add(string.Join(" · ", source));
        if (options.ShowName)
        {
            string name = tile.Name;
            if (options.NameOverrides.TryGetValue(tile.Key, out var custom)) name = custom;
            else if (options.UseChatNames && tile.Host == "local" && tile.Client == "codex" &&
                     tile.Kind != "subagent" && chatNames is not null &&
                     chatNames.TryGetValue(tile.SessionId, out var saved)) name = saved;
            lines.Add((tile.Kind == "subagent" ? "> " : "") + name);
        }
        return new(string.Join("\n", lines), options.ShowStatus ? tile.Status : "");
    }

    public static (int Header, int Footer) LabelHeights(ButtonLabels labels, int height)
    {
        int header = labels.Header.Length == 0 ? 0 :
            labels.Header.Contains('\n') ? Math.Max(24, height / 3) : Math.Max(18, height / 5);
        int footer = labels.Footer.Length == 0 ? 0 : Math.Max(16, height / 6);
        footer = Math.Min(footer, height / 4);
        header = Math.Min(header, Math.Max(0, height - footer - 8));
        return (header, footer);
    }

    public static (string State, bool Moves) Animation(string status) => status switch
    {
        "WORKING" or "TOOL" or "COMPACT" => ("running", true),
        "APPROVAL?" => ("waiting", true),
        "TURN STOP" or "STOPPED" => ("review", true),
        "EXIT ERROR" or "TURN ERROR" => ("failed", true),
        "READY" => ("idle", true),
        _ => ("idle", false) // stale/offline/closed never appear to keep working
    };
    public static int Frame(int count, int fps, bool animate, double seconds)
    {
        if (count < 1 || fps is < 1 or > 8) throw new ArgumentOutOfRangeException();
        return !animate || !double.IsFinite(seconds) ? 0 : (int)(Math.Floor(Math.Max(0, seconds)*fps) % count);
    }
    public static byte[] ReadPng(string path, int width, int height)
    {
        if (new FileInfo(path).Length > 1024*1024) throw new InvalidDataException("Frame exceeds 1 MiB");
        var b = File.ReadAllBytes(path);
        byte[] signature = { 137, 80, 78, 71, 13, 10, 26, 10 };
        if (b.Length < 24 || !b.AsSpan(0, 8).SequenceEqual(signature) ||
            !b.AsSpan(12, 4).SequenceEqual("IHDR"u8) ||
            BinaryPrimitives.ReadUInt32BigEndian(b.AsSpan(16, 4)) != width ||
            BinaryPrimitives.ReadUInt32BigEndian(b.AsSpan(20, 4)) != height)
            throw new InvalidDataException("Frame PNG geometry differs from manifest");
        return b;
    }
}
