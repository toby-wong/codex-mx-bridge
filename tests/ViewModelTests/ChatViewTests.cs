using System.Text.Json;
using Loupedeck.CodexMxPlugin;

internal static class ChatViewTests
{
    public static int Run()
    {
        int count = 0;
        void Check(bool condition, string message)
        {
            if (!condition) throw new Exception(message);
            count++;
        }
        var state = new State { SchemaVersion = 1, Rows = Enumerable.Range(1, 12).Select(i =>
            new Row { Key = $"chat-{i:D2}", SessionId = $"native-{i}", Name = $"Chat {i}",
                Order = i, CreatedAt = i, UpdatedAt = 100 + i, ValidUntil = 1000,
                Herdr = true, HerdrSocket = "/tmp/herdr.sock" }).ToList() };
        var paged = ViewModel.Tiles(state, 200);
        Check(paged.Count == 12 && ViewModel.PageCount(paged.Count) == 2 &&
              paged[0].Key == "chat-01", "paged mode retains every row in registration order");
        state.Rows[0].UpdatedAt = 150;
        var recent = ViewModel.Tiles(state, 200, "recent");
        Check(recent.Count == 9 && recent[0].Key == "chat-01" && recent[1].Key == "chat-12",
              "recent mode limits to the nine latest activity times");
        Check(recent[0] is { SessionId: "native-1", HerdrSocket: "/tmp/herdr.sock", Herdr: true },
              "sorting preserves the exact focus identity");
        Check(ViewModel.WrapPage(1, recent.Count) == 0, "switching from page two yields one recent page");
        Check(ViewModel.Tiles(state, 200).Count == 12 && state.Rows[0].Order == 1,
              "filtering is a view and never deletes or reorders stored history");

        var newest = ViewModel.Tiles(state, 200, "newest");
        Check(newest[0].Key == "chat-12" && !newest.Any(t => t.Key == "chat-01"),
              "resuming an older chat does not make it newly started");
        state.Rows[11].CreatedAt = null;
        state.Rows[11].UpdatedAt = 999;
        newest = ViewModel.Tiles(state, 200, "newest");
        Check(newest[0].Key == "chat-11" && !newest.Any(t => t.Key == "chat-12"),
              "legacy rows never use recent activity as an invented creation time");
        foreach (var row in state.Rows) row.CreatedAt = null;
        newest = ViewModel.Tiles(state, 200, "newest");
        Check(newest[0].Key == "chat-12" && newest[1].Key == "chat-11",
              "all-legacy history falls back to newest registration per source");

        state.Rows[11].Status = "CLOSED";
        state.Rows[10].Status = "EXIT ERROR";
        state.Rows[9].Status = "STOPPED";
        state.Rows[8].Status = "TURN STOP";
        state.Rows[7].Status = "TURN ERROR";
        var open = ViewModel.Tiles(state, 200, "recent_open");
        Check(open.Count == 9 && !open.Any(t => t.Status is "CLOSED" or "EXIT ERROR" or "STOPPED"),
              "recent_open excludes ended sessions and stopped child agents");
        Check(open.Any(t => t.Status == "TURN STOP") && open.Any(t => t.Status == "TURN ERROR"),
              "an ended turn is still an open conversation");
        Check(ViewModel.Tiles(state, 200, "recent")[0].Status == "CLOSED",
              "unfiltered recent activity includes a recently closed session");

        state.Remotes["desktop"] = new Remote { ReceivedAt = 200, Rows = new() {
            new() { Key = "chat-01", UpdatedAt = 1500, CreatedAt = 20, ValidUntil = 1000,
                    ItermId = "untrusted", Herdr = true, SessionId = "native-1",
                    HerdrSocket = "/tmp/injected.sock", Client = "kiro" }
        }};
        var remote = ViewModel.Tiles(state, 200, "recent")[0];
        Check(remote.Key == "remote/desktop/chat-01" && remote.Client == "kiro",
              "recent activity merges normalized local and remote times without ID collisions");
        Check(remote is { Herdr: false, ItermId: "", SessionId: "", HerdrSocket: "" },
              "a recent remote tile cannot acquire a local focus target");
        Check(ViewModel.Tiles(state, 200, "newest")[0].Key == remote.Key,
              "known remote creation times participate in newest sorting");
        state.Remotes["desktop"].Rows[0].Status = "CLOSED";
        state.Remotes["desktop"].Error = "offline";
        Check(!ViewModel.Tiles(state, 200, "recent_open").Any(t => t.Key == remote.Key),
              "offline presentation cannot hide a remote row's recorded completion from the filter");
        state.Remotes["desktop"].Rows[0].Status = "WORKING";
        Check(ViewModel.Tiles(state, 200, "recent_open")[0].Status == "OFFLINE",
              "unknown offline liveness is not treated as a closed conversation");
        state.Remotes.Clear();
        state.Rows[0].UpdatedAt = state.Rows[1].UpdatedAt = 2000;
        Check(ViewModel.Tiles(state, 200, "recent")[0].Key == "chat-01",
              "equal activity times have a deterministic key tie break");

        var targets = new ButtonTargets();
        var before = ViewModel.Tiles(state, 200, "recent")[0];
        targets.Displayed(0, before);
        state.Rows[2].UpdatedAt = 3000;
        var after = ViewModel.Tiles(state, 200, "recent")[0];
        Check(after.Key != before.Key && targets.Get(0)?.SessionId == before.SessionId,
              "activity reordering cannot retarget a button before a replacement image is rendered");
        targets.Displayed(0, after);
        Check(targets.Get(0)?.SessionId == after.SessionId,
              "the next completed render updates the button's native focus identity");
        targets.Displayed(0, null);
        Check(targets.Get(0) is null, "an empty rendered slot does not retain an old focus target");

        var diagnostics = new State { SchemaVersion = 1, DroppedRows = 4 };
        diagnostics.Remotes["offline"] = new Remote { Error = "offline" };
        Check(ViewModel.Tiles(diagnostics, 200, "recent").Count == 2,
              "diagnostics remain available when recent chat positions are unused");
        state.DroppedRows = 4;
        Check(ViewModel.Tiles(state, 200, "recent").All(t => t.Host != "bridge"),
              "history diagnostics do not evict one of nine recent chats");
        foreach (string view in new[] { "paged", "recent", "recent_open", "newest" })
            Check(DisplayOptions.Parse(JsonSerializer.Serialize(new { schema_version = 1, chat_view = view }))
                  .ChatView == view, "every documented view is accepted");
        try { DisplayOptions.Parse("{\"schema_version\":1,\"chat_view\":\"invalid\"}"); }
        catch (JsonException) { count++; return count; }
        throw new Exception("Invalid chat view accepted");
    }
}
