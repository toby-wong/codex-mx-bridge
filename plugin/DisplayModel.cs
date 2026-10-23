using System.Buffers.Binary;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Loupedeck.CodexMxPlugin;

public sealed class DisplayOptions
{
    public int SchemaVersion { get; set; }
    public string Mode { get; set; } = "text";
    public string Pet { get; set; } = "";
    public int Fps { get; set; } = 4;
    public bool Animate { get; set; } = true;
    public static DisplayOptions Parse(string text)
    {
        var o = JsonSerializer.Deserialize<DisplayOptions>(text, ViewModel.Json) ?? throw new JsonException("Missing display config");
        if (o.SchemaVersion != 1 || o.Mode is not ("text" or "pet") || o.Pet is null ||
            o.Fps is < 1 or > 8 || (o.Pet.Length > 0 && !Regex.IsMatch(o.Pet, @"\A[a-zA-Z0-9_-]{1,48}/[a-f0-9]{16}\z")) ||
            (o.Mode == "pet" && o.Pet.Length == 0))
            throw new JsonException("Invalid display mode, pet revision or frame rate");
        return o;
    }
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
    public static (string State, bool Moves) Animation(string status) => status switch
    {
        "WORKING" or "TOOL" or "COMPACT" => ("running", true),
        "APPROVAL?" => ("waiting", true),
        "TURN STOP" or "STOPPED" => ("review", true),
        "EXIT ERROR" => ("failed", true),
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
