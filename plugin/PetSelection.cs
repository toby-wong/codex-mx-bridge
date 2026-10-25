using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace Loupedeck.CodexMxPlugin;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed class PetRule
{
    public string Pet { get; set; } = "";
    public string Location { get; set; } = "";
    public string Client { get; set; } = "";
    public string Host { get; set; } = "";
    public string Key { get; set; } = "";
}

public static class PetSelection
{
    public static bool ValidReference(string? value) => value is not null &&
        Regex.IsMatch(value, @"\A[a-zA-Z0-9_-]{1,48}(?:/[a-f0-9]{16})?\z");

    public static IEnumerable<string> References(DisplayOptions options) =>
        new[] { options.Pet }.Concat(options.PetRules.Select(r => r.Pet))
            .Where(p => p.Length > 0).Distinct(StringComparer.Ordinal);

    public static void Validate(DisplayOptions options)
    {
        bool Selector(string? value, int limit) => value is not null && value.Length <= limit &&
            (value.Length == 0 || (!string.IsNullOrWhiteSpace(value) && !value.Any(char.IsControl)));
        if (options.PetRules is null || options.PetRules.Count > 64)
            throw new JsonException("pet_rules must contain at most 64 rules");
        foreach (var rule in options.PetRules)
        {
            if (rule is null || !ValidReference(rule.Pet) ||
                rule.Location is not ("" or "local" or "remote") ||
                rule.Client is not ("" or "codex" or "claude" or "kiro") ||
                !Selector(rule.Host, 255) || !Selector(rule.Key, 700) ||
                (rule.Location.Length + rule.Client.Length + rule.Host.Length + rule.Key.Length == 0) ||
                (rule.Host.Length > 0 && rule.Location == "local"))
                throw new JsonException("Invalid pet rule: choose a pet and location, client, remote host or chat key");
        }
        if (References(options).Count() > 16)
            throw new JsonException("Configure at most 16 distinct pet references");
    }

    // Every supplied selector must match. Later matching rules override earlier ones.
    public static string? For(Tile tile, DisplayOptions options)
    {
        if (options.Mode != "pet" || (tile.RemoteHost is null && tile.Host == "bridge")) return null;
        bool remote = tile.RemoteHost is not null || tile.Host != "local";
        string host = tile.RemoteHost ?? tile.Host;
        string pet = options.Pet;
        foreach (var rule in options.PetRules)
            if ((rule.Location.Length == 0 || rule.Location == (remote ? "remote" : "local")) &&
                (rule.Client.Length == 0 || rule.Client == tile.Client) &&
                (rule.Host.Length == 0 || (remote && rule.Host == host)) &&
                (rule.Key.Length == 0 || rule.Key == tile.Key))
                pet = rule.Pet;
        return pet;
    }

    public static string Resolve(string root, string reference)
    {
        if (!ValidReference(reference)) throw new InvalidDataException("Invalid pet reference");
        string id = reference;
        if (!reference.Contains('/'))
        {
            string folder = Path.Combine(root, "pets", reference);
            var matches = Directory.Exists(folder)
                ? Directory.EnumerateDirectories(folder)
                    .Where(p => Regex.IsMatch(Path.GetFileName(p), @"\A[a-f0-9]{16}\z") &&
                        File.Exists(Path.Combine(p, "manifest.json"))).Take(2).ToArray()
                : Array.Empty<string>();
            if (matches.Length != 1)
                throw new InvalidDataException($"Pet '{reference}' is missing or has several revisions; use an ID from pet list");
            id = reference + "/" + Path.GetFileName(matches[0]);
        }
        if (!File.Exists(Path.Combine(root, "pets", id.Replace('/', Path.DirectorySeparatorChar), "manifest.json")))
            throw new InvalidDataException($"Imported pet manifest is missing: {id}");
        return id;
    }
}

public sealed record PetPack(string Id, PetManifest Manifest, Dictionary<string, byte[]> Frames)
{
    public const long MaxLoadedPixels = 32L * 1024 * 1024;
    public long Pixels => (long)Manifest.FrameWidth * Manifest.FrameHeight * Frames.Count;

    public static PetPack Load(string root, string reference, long availablePixels = MaxLoadedPixels)
    {
        string id = PetSelection.Resolve(root, reference);
        string folder = Path.Combine(root, "pets", id.Replace('/', Path.DirectorySeparatorChar));
        string path = Path.Combine(folder, "manifest.json");
        if (new FileInfo(path).Length > DisplayOptions.MaxBytes)
            throw new InvalidDataException("Oversize pet manifest");
        var manifest = PetManifest.Parse(File.ReadAllText(path));
        var files = manifest.Animations.Values.SelectMany(v => v).Distinct().ToArray();
        if ((long)manifest.FrameWidth * manifest.FrameHeight * files.Length > availablePixels)
            throw new InvalidDataException("Selected pets exceed the loaded frame pixel limit");
        var frames = files.ToDictionary(file => file, file =>
            DisplayPlan.ReadPng(Path.Combine(folder, file), manifest.FrameWidth, manifest.FrameHeight));
        return new(id, manifest, frames);
    }
}
