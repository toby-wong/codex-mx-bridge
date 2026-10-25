using Loupedeck.CodexMxPlugin;
using System.Text.Json;

int count = 0;
void Check(bool result, string name) { if (!result) throw new Exception(name); count++; }
var state = new State { SchemaVersion = 1, Rows = new() {
    new() { Key = "a", Name = "hello", Status = "WORKING", ValidUntil = 150, Order = 1, ItermId = "abc" },
    new() { Key = "b", Status = "CLOSED", ValidUntil = 0, Order = 2 },
    new() { Key = "c", Herdr = true, ItermId = "obsolete", ValidUntil = 150, Order = 3,
            SessionId = "herdr-chat", HerdrSocket = "/tmp/herdr.sock" }
}};
Check(ViewModel.Tiles(state, 100)[0].Status == "WORKING", "live status");
Check(ViewModel.Tiles(state, 200)[0].Status == "STALE", "expired heartbeat");
Check(ViewModel.Tiles(state, 200)[1].Status == "CLOSED", "closed remains closed");
Check(ViewModel.Tiles(state, 100)[2].ItermId == "", "Herdr target suppressed");
Check(ViewModel.Tiles(state, 100)[2] is { Herdr: true, SessionId: "herdr-chat", HerdrSocket: "/tmp/herdr.sock" },
      "local Herdr identity reaches the button");
state.Remotes["linux"] = new Remote { ReceivedAt = 100, Rows = new() {
    new() { Key = "a", Status = "TOOL", ValidUntil = 200, ItermId = "bad", Herdr = true,
            SessionId = "herdr-chat", HerdrSocket = "/tmp/injected.sock" } } };
Check(ViewModel.Tiles(state, 110)[3].Status == "TOOL", "remote connected");
Check(ViewModel.Tiles(state, 116)[3].Status == "OFFLINE", "collector disappeared");
Check(ViewModel.Tiles(state, 110)[3].ItermId == "", "remote cannot focus local pane");
Check(ViewModel.Tiles(state, 110)[3] is { Herdr: false, SessionId: "", HerdrSocket: "" },
      "remote cannot supply Herdr focus identity");
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
if (args.Length == 1)
{
    var wire = ViewModel.Parse(File.ReadAllText(args[0]));
    Check(wire.Rows.Count > 0, "Python to C# contract fixture");
    Check(ViewModel.Tiles(wire, DateTimeOffset.UtcNow.ToUnixTimeSeconds()).Count > 0, "Python tiles");
    var options = HerdrFocusOptions.Parse(File.ReadAllText(Path.Combine(Path.GetDirectoryName(args[0])!, "herdr-focus.json")));
    var herdr = wire.Rows.Single(r => r.Herdr);
    Check(herdr.HerdrSocket == options.Bindings.Single().SocketPath, "Python Herdr socket/binding contract");
    Check(herdr.SessionId == "herdr-contract", "Python native session identity contract");
}
Console.WriteLine($"PASS: {count} view-model checks");

int spriteChecks = 0;
void SpriteCheck(bool result, string name) { if (!result) throw new Exception(name); spriteChecks++; }
SpriteCheck(DisplayOptions.Parse("{\"schema_version\":1,\"mode\":\"text\"}").Fps == 4, "default fps");
SpriteCheck(DisplayOptions.Parse("{\"schema_version\":1,\"mode\":\"pet\",\"pet\":\"buddy/0123456789abcdef\",\"animate\":false}").Animate == false, "still mode");
foreach (string config in new[] {
    "{}", "{\"schema_version\":2}", "{\"schema_version\":1,\"mode\":\"pet\"}",
    "{\"schema_version\":1,\"pet\":\"../../bad\"}", "{\"schema_version\":1,\"fps\":60}" })
{
    try { DisplayOptions.Parse(config); throw new Exception("bad display accepted"); }
    catch (JsonException) { spriteChecks++; }
}
SpriteCheck(DisplayPlan.Animation("APPROVAL?") == ("waiting", true), "permission pose");
SpriteCheck(DisplayPlan.Animation("WORKING") == ("running", true), "work pose");
SpriteCheck(DisplayPlan.Animation("TURN STOP") == ("review", true), "stop is review, not success");
SpriteCheck(DisplayPlan.Animation("EXIT ERROR") == ("failed", true), "error pose");
SpriteCheck(DisplayPlan.Animation("OFFLINE") == ("idle", false), "offline stays still");
SpriteCheck(DisplayPlan.Frame(6, 4, true, 0.24) == 0 && DisplayPlan.Frame(6, 4, true, 0.25) == 1, "frame pacing");
SpriteCheck(DisplayPlan.Frame(6, 4, true, 1.5) == 0, "loop wraps");
SpriteCheck(DisplayPlan.Frame(6, 4, false, 100) == 0, "reduced motion");
SpriteCheck(DisplayPlan.Frame(6, 4, true, double.NaN) == 0, "invalid time");
var manifest = new PetManifest { SchemaVersion = 1, FrameWidth = 192, FrameHeight = 208,
    Animations = new() { ["idle"] = new[] { "idle-0.png" }, ["running"] = new[] { "running-0.png" },
    ["waiting"] = new[] { "waiting-0.png" }, ["review"] = new[] { "review-0.png" }, ["failed"] = new[] { "failed-0.png" } } };
SpriteCheck(PetManifest.Parse(JsonSerializer.Serialize(manifest, ViewModel.Json)).Animations.Count == 5, "manifest contract");
manifest.Animations["idle"] = new[] { "../secret.png" };
try { PetManifest.Parse(JsonSerializer.Serialize(manifest, ViewModel.Json)); throw new Exception("path traversal accepted"); }
catch (JsonException) { spriteChecks++; }
Console.WriteLine($"PASS: {spriteChecks} sprite display checks");
Console.WriteLine($"PASS: {await FocusTests.Run()} Herdr focus checks");
Console.WriteLine($"PASS: {await SocketTests.Run()} Herdr socket checks");
if (args is ["--probe-herdr", var socket]) await FocusTests.Probe(socket);
