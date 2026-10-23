using Loupedeck.CodexMxPlugin;
using System.Text.Json;

int count = 0;
void Check(bool result, string name) { if (!result) throw new Exception(name); count++; }
var state = new State { SchemaVersion = 1, Rows = new() {
    new() { Key = "a", Name = "hello", Status = "WORKING", ValidUntil = 150, Order = 1, ItermId = "abc" },
    new() { Key = "b", Status = "CLOSED", ValidUntil = 0, Order = 2 },
    new() { Key = "c", Herdr = true, ItermId = "obsolete", ValidUntil = 150, Order = 3 }
}};
Check(ViewModel.Tiles(state, 100)[0].Status == "WORKING", "live status");
Check(ViewModel.Tiles(state, 200)[0].Status == "STALE", "expired heartbeat");
Check(ViewModel.Tiles(state, 200)[1].Status == "CLOSED", "closed remains closed");
Check(ViewModel.Tiles(state, 100)[2].ItermId == "", "Herdr target suppressed");
state.Remotes["linux"] = new Remote { ReceivedAt = 100, Rows = new() { new() { Key = "a", Status = "TOOL", ValidUntil = 200, ItermId = "bad" } } };
Check(ViewModel.Tiles(state, 110)[3].Status == "TOOL", "remote connected");
Check(ViewModel.Tiles(state, 116)[3].Status == "OFFLINE", "collector disappeared");
Check(ViewModel.Tiles(state, 110)[3].ItermId == "", "remote cannot focus local pane");
state.Remotes["linux"].Error = "SSH timeout";
Check(ViewModel.Tiles(state, 110)[3].Status == "OFFLINE", "SSH failure is immediate");
Check(ViewModel.PageCount(9) == 1 && ViewModel.PageCount(10) == 2, "pagination");
Check(ViewModel.WrapPage(-1, 20) == 2, "negative page wraps");
Check(ViewModel.WrapPage(4, 0) == 0, "empty page");
Check(ViewModel.Short("a\nb") == "ab", "control characters");
var roundtrip = ViewModel.Parse(JsonSerializer.Serialize(state, ViewModel.Json));
Check(roundtrip.Rows[0].ItermId == "abc", "wire property naming");
try { ViewModel.Parse("{\"schema_version\":2}"); throw new Exception("schema accepted"); }
catch (JsonException) { count++; }
if (args.Length > 0)
{
    var wire = ViewModel.Parse(File.ReadAllText(args[0]));
    Check(wire.Rows.Count > 0, "Python to C# contract fixture");
    Check(ViewModel.Tiles(wire, DateTimeOffset.UtcNow.ToUnixTimeSeconds()).Count > 0, "Python tiles");
}
Console.WriteLine($"PASS: {count} view-model checks");
