using System.Globalization;
using System.Text.Json;

namespace Loupedeck.CodexMxPlugin;

public sealed class Row
{
    public string Key { get; set; } = "";
    public string SessionId { get; set; } = "";
    public string Name { get; set; } = "Codex";
    public string Kind { get; set; } = "session";
    public string Client { get; set; } = "codex";
    public string Status { get; set; } = "READY";
    public string LastEvent { get; set; } = "";
    public string ItermId { get; set; } = "";
    public string Tty { get; set; } = "";
    public string HerdrSocket { get; set; } = "";
    public long Order { get; set; }
    public double UpdatedAt { get; set; }
    public double? CreatedAt { get; set; }
    public double ValidUntil { get; set; }
    public bool Herdr { get; set; }
}

public sealed class Remote
{
    public List<Row> Rows { get; set; } = new();
    public double ReceivedAt { get; set; }
    public string Error { get; set; } = "";
}

public sealed class State
{
    public int SchemaVersion { get; set; }
    public List<Row> Rows { get; set; } = new();
    public Dictionary<string, Remote> Remotes { get; set; } = new();
    public int DroppedRows { get; set; }
}

public sealed record Tile(string Key, string Name, string Status, string Host,
                          string ItermId = "", string Tty = "", string Kind = "session",
                          bool Herdr = false, string SessionId = "", string HerdrSocket = "",
                          string Client = "codex", string? RemoteHost = null)
{
    public string Header => Client switch
    {
        "claude" => $"Claude · {Host}",
        "kiro" => $"Kiro · {Host}",
        _ => Host
    };
    public string Text => $"{Header}\n{(Kind == "subagent" ? "> " : "")}{Name}\n{Status}";
}

public static class ViewModel
{
    public static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly HashSet<string> Final = new() { "CLOSED", "EXIT ERROR", "STOPPED" };

    public static State Parse(string text)
    {
        var state = JsonSerializer.Deserialize<State>(text, Json) ?? throw new JsonException("Missing state");
        if (state.SchemaVersion != 1 || state.Rows is null || state.Remotes is null)
            throw new JsonException("Unsupported bridge schema");
        return state;
    }

    public static List<Tile> Tiles(State state, double now, string chatView = "paged")
    {
        var list = new List<(Tile Tile, Row? Row, string Source)>();
        string Status(Row r) => !Final.Contains(r.Status) && now > r.ValidUntil ? "STALE" : r.Status;
        foreach (var r in state.Rows.OrderBy(r => r.Order))
            list.Add((new(r.Key, Short(r.Name, 80), Status(r), "local", r.Herdr ? "" : r.ItermId,
                         r.Herdr ? "" : r.Tty, r.Kind, r.Herdr, r.SessionId,
                         r.Herdr ? r.HerdrSocket : "", r.Client), r, "local"));
        foreach (var (host, remote) in state.Remotes.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            bool offline = remote.Error.Length > 0 || now > remote.ReceivedAt + 15;
            if (remote.Rows.Count == 0 && offline)
                list.Add((new("remote/" + host, "SSH", "OFFLINE", Short(host), RemoteHost: host), null, host));
            foreach (var r in remote.Rows.OrderBy(r => r.Order))
                list.Add((new("remote/" + host + "/" + r.Key, Short(r.Name, 80),
                    offline ? "OFFLINE" : Status(r), Short(host), Kind: r.Kind, Client: r.Client,
                    RemoteHost: host), r, host));
        }
        if (state.DroppedRows > 0)
            list.Add((new("overflow", "History cap", "PRUNED " + state.DroppedRows, "bridge"), null, "bridge"));
        if (chatView == "paged") return list.Select(c => c.Tile).ToList();
        if (chatView is not ("recent" or "recent_open" or "newest"))
            throw new ArgumentException("Unknown chat view", nameof(chatView));

        var chats = list.Where(c => c.Row is not null &&
            (chatView != "recent_open" || !Final.Contains(c.Row.Status)));
        // Activity and creation are separate: a resumed old chat is not new.
        // Old rows without creation times follow dated rows, grouped by source
        // and newest registration first; activity is never used as a fake start.
        var ordered = chatView == "newest"
            ? chats.OrderByDescending(c => c.Row!.CreatedAt ?? double.NegativeInfinity)
                   .ThenBy(c => c.Source, StringComparer.Ordinal)
                   .ThenByDescending(c => c.Row!.Order)
                   .ThenBy(c => c.Tile.Key, StringComparer.Ordinal)
            : chats.OrderByDescending(c => c.Row!.UpdatedAt)
                   .ThenBy(c => c.Tile.Key, StringComparer.Ordinal);
        // Diagnostics can fill unused positions but do not evict recent chats.
        return ordered.Select(c => c.Tile).Concat(list.Where(c => c.Row is null).Select(c => c.Tile))
                      .Take(9).ToList();
    }

    public static string Short(string text, int limit = 18)
    {
        if (limit <= 0) return "";
        string clean = new(text.Where(c => !char.IsControl(c)).ToArray());
        if (clean.Length <= limit) return clean;
        // A name can reach this cap before label fitting; retain complete
        // graphemes so the renderer never receives half an emoji or accent.
        int end = 0;
        foreach (int boundary in StringInfo.ParseCombiningCharacters(clean))
        {
            if (boundary > limit) break;
            end = boundary;
        }
        return clean[..end];
    }
    public static int PageCount(int count) => Math.Max(1, (count + 8) / 9);
    public static int WrapPage(int page, int count) => ((page % PageCount(count)) + PageCount(count)) % PageCount(count);
}

public sealed class ButtonTargets
{
    private readonly Tile?[] _displayed = new Tile?[9];
    public Tile? Get(int slot) => Volatile.Read(ref _displayed[slot]);
    public void Displayed(int slot, Tile? tile) => Volatile.Write(ref _displayed[slot], tile);
}
