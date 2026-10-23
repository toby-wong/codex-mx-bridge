using System.Text.Json;

namespace Loupedeck.CodexMxPlugin;

public sealed class Row
{
    public string Key { get; set; } = "";
    public string SessionId { get; set; } = "";
    public string Name { get; set; } = "Codex";
    public string Kind { get; set; } = "session";
    public string Status { get; set; } = "READY";
    public string LastEvent { get; set; } = "";
    public string ItermId { get; set; } = "";
    public string Tty { get; set; } = "";
    public long Order { get; set; }
    public double UpdatedAt { get; set; }
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
                          string ItermId = "", string Tty = "", string Kind = "session")
{
    public string Text => $"{Host}\n{(Kind == "subagent" ? "> " : "")}{Name}\n{Status}";
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

    public static List<Tile> Tiles(State state, double now)
    {
        var list = new List<Tile>();
        string Status(Row r) => !Final.Contains(r.Status) && now > r.ValidUntil ? "STALE" : r.Status;
        foreach (var r in state.Rows.OrderBy(r => r.Order))
            list.Add(new(r.Key, Short(r.Name), Status(r), "local", r.Herdr ? "" : r.ItermId,
                         r.Herdr ? "" : r.Tty, r.Kind));
        foreach (var (host, remote) in state.Remotes.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            bool offline = remote.Error.Length > 0 || now > remote.ReceivedAt + 15;
            if (remote.Rows.Count == 0 && offline)
                list.Add(new("remote/" + host, "SSH", "OFFLINE", Short(host)));
            foreach (var r in remote.Rows.OrderBy(r => r.Order))
                list.Add(new("remote/" + host + "/" + r.Key, Short(r.Name),
                    offline ? "OFFLINE" : Status(r), Short(host), Kind: r.Kind));
        }
        if (state.DroppedRows > 0)
            list.Add(new("overflow", "History cap", "PRUNED " + state.DroppedRows, "bridge"));
        return list;
    }

    public static string Short(string text) => new(text.Where(c => !char.IsControl(c)).Take(18).ToArray());
    public static int PageCount(int count) => Math.Max(1, (count + 8) / 9);
    public static int WrapPage(int page, int count) => ((page % PageCount(count)) + PageCount(count)) % PageCount(count);
}
