using System.Diagnostics;

namespace Loupedeck.CodexMxPlugin;

// Loupedeck is the namespace used by the official Logitech Actions C# SDK.
public sealed class CodexMxPlugin : Plugin
{
    public override bool UsesApplicationApiOnly => true;
    public override bool HasNoApplication => true;
    private CancellationTokenSource? _stop;
    private Task? _poll;
    public override void Load()
    {
        _stop = new();
        var token = _stop.Token;
        _poll = Task.Run(async () =>
        {
            int tick = 0;
            while (!token.IsCancellationRequested)
            {
                if (tick++ % 4 == 0) Dashboard.Refresh();
                Dashboard.Animate();
                try { await Task.Delay(125, token); }
                catch (OperationCanceledException) { break; }
            }
        }, token);
    }
    public override void Unload()
    {
        _stop?.Cancel();
        try { _poll?.Wait(TimeSpan.FromSeconds(2)); } catch (AggregateException) { }
        _stop?.Dispose();
        _stop = null;
        PetDisplay.Clear();
    }
}

public sealed class CodexMxApplication : ClientApplication
{
    protected override string GetProcessName() => "iTerm2";
    protected override string GetBundleName() => "com.googlecode.iterm2";
}

internal static class Dashboard
{
    private static readonly object Gate = new();
    private static List<Tile> _tiles = new();
    private static string _fingerprint = "";
    private static int _page;
    private static readonly string?[] FrameKeys = new string?[9];
    private static string _focusError = "";
    private static int _focusing;
    private static readonly string Home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    public static event Action? Changed;
    public static event Action<int>? SlotFrameChanged;
    public static string StatePath => Path.Combine(Environment.GetEnvironmentVariable("MX_CODEX_STATE_DIR") ??
        Path.Combine(Home, ".local", "state", "codex-mx-bridge"), "state.json");
    public static void Refresh()
    {
        bool styleChanged = PetDisplay.Refresh(Path.GetDirectoryName(StatePath)!);
        List<Tile> tiles;
        try
        {
            var file = new FileInfo(StatePath);
            if (file.Length > 4 * 1024 * 1024) throw new InvalidDataException("Oversize state");
            tiles = ViewModel.Tiles(ViewModel.Parse(File.ReadAllText(StatePath)),
                DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0, PetDisplay.ChatView);
        }
        catch (FileNotFoundException) { tiles = new() { new("missing", "Install hooks", "NO DATA", "bridge") }; }
        catch (DirectoryNotFoundException) { tiles = new() { new("missing", "Install hooks", "NO DATA", "bridge") }; }
        catch (Exception ex) when (ex is IOException or System.Text.Json.JsonException or UnauthorizedAccessException)
        { tiles = new() { new("error", "Check state", "READ ERROR", "bridge") }; }
        lock (Gate)
        {
            var fingerprint = System.Text.Json.JsonSerializer.Serialize(tiles);
            if (fingerprint == _fingerprint && !styleChanged) return;
            _fingerprint = fingerprint;
            _tiles = tiles;
            _page = ViewModel.WrapPage(_page, _tiles.Count);
        }
        Notify();
    }
    public static void Animate()
    {
        for (int i = 0; i < 9; i++)
        {
            var key = PetDisplay.FrameKey(Get(i));
            bool changed;
            lock (Gate) { changed = key != FrameKeys[i]; FrameKeys[i] = key; }
            if (!changed || key is null) continue;
            foreach (Action<int> callback in SlotFrameChanged?.GetInvocationList() ?? Array.Empty<Delegate>())
                try { callback(i); } catch (Exception ex) { Trace.WriteLine(ex.Message); }
        }
    }
    private static void Notify()
    {
        // SDK redraw callbacks must never kill the polling task.
        foreach (Action callback in Changed?.GetInvocationList() ?? Array.Empty<Delegate>())
            try { callback(); } catch (Exception ex) { Trace.WriteLine(ex.Message); }
    }
    public static Tile? Get(int slot)
    {
        lock (Gate)
        {
            int i = _page * 9 + slot;
            return i >= 0 && i < _tiles.Count ? _tiles[i] : null;
        }
    }
    public static string PageText { get { lock (Gate) return $"{_page + 1}/{ViewModel.PageCount(_tiles.Count)}"; } }
    public static void Move(int diff)
    {
        lock (Gate) _page = ViewModel.WrapPage(_page + Math.Sign(diff), _tiles.Count);
        Notify();
    }
    public static void Focus(Tile? tile)
    {
        if (tile is null || Interlocked.CompareExchange(ref _focusing, 1, 0) != 0) return;
        _ = Task.Run(async () =>
        {
            string error = "", success = "Focused iTerm";
            try
            {
                var script = FocusScript.Read(typeof(CodexMxPlugin).Assembly);
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(8));
                if (tile.Herdr)
                {
                    var path = Path.Combine(Path.GetDirectoryName(StatePath)!, "herdr-focus.json");
                    if (!File.Exists(path))
                        throw new InvalidOperationException("Bind this Herdr session with codex-mx herdr-focus bind.");
                    if (new FileInfo(path).Length > 65536)
                        throw new InvalidDataException("Herdr focus configuration exceeds 64 KiB");
                    var options = HerdrFocusOptions.Parse(File.ReadAllText(path));
                    await using var transport = new HerdrTransport();
                    string pane = await HerdrFocus.FocusAsync(tile, options, transport.RequestAsync,
                        (id, tty, check, token) => FocusIterm(script, id, tty, check, token), deadline.Token);
                    success = $"Focused Herdr {pane} and iTerm" +
                        (tile.RemoteHost is null ? "" : $" via SSH ({tile.RemoteHost})");
                }
                else
                {
                    if (tile.ItermId.Length == 0 && tile.Tty.Length == 0)
                        throw new InvalidOperationException("No direct iTerm target; remote focus is not configured.");
                    await FocusIterm(script, tile.ItermId.Split(':').Last(), tile.Tty, false, deadline.Token);
                }
            }
            catch (OperationCanceledException) { error = "Terminal focus timed out"; }
            catch (Exception ex) { error = ex.Message; }
            _focusError = error;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(StatePath)!);
                File.WriteAllText(Path.Combine(Path.GetDirectoryName(StatePath)!, "focus-status.txt"),
                    DateTimeOffset.UtcNow.ToString("O") + " " + (error.Length == 0 ? success : error) +
                    $" | client={tile.Client}; key={tile.Key}; session={tile.SessionId}; host={tile.Host}");
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
            finally { Interlocked.Exchange(ref _focusing, 0); }
            Notify();
        });
    }
    private static async Task FocusIterm(string script, string id, string tty, bool checkOnly,
                                          CancellationToken cancellation)
    {
        var start = new ProcessStartInfo("/usr/bin/osascript")
        {
            UseShellExecute = false, RedirectStandardInput = true,
            RedirectStandardError = true, RedirectStandardOutput = true
        };
        start.ArgumentList.Add("-");
        // Pass data through argv, never interpolate AppleScript or shell code.
        start.ArgumentList.Add(id);
        start.ArgumentList.Add(tty);
        start.ArgumentList.Add(checkOnly ? "check" : "focus");
        using var process = Process.Start(start) ?? throw new IOException("Cannot start osascript");
        var stdout = process.StandardOutput.ReadToEndAsync(cancellation);
        var stderr = process.StandardError.ReadToEndAsync(cancellation);
        try
        {
            await process.StandardInput.WriteAsync(script.AsMemory(), cancellation);
            await process.StandardInput.FlushAsync(cancellation);
            process.StandardInput.Close();
            await process.WaitForExitAsync(cancellation);
            await Task.WhenAll(stdout, stderr);
        }
        catch
        {
            if (!process.HasExited) process.Kill();
            throw;
        }
        if (process.ExitCode != 0)
            throw new IOException("iTerm target missing or macOS Automation permission denied.");
    }
    public static string FocusStatus => _focusError.Length > 0 ? "NO FOCUS" : "";
}

public sealed class AgentSlotCommand : PluginDynamicCommand
{
    private readonly ButtonTargets _targets = new();
    public AgentSlotCommand()
    {
        // The live image already contains the labels; use the full button surface.
        IsWidget = true;
        for (int i = 0; i < 9; i++) AddParameter(i.ToString(), $"Agent slot {i + 1}", "Agents");
    }
    protected override bool OnLoad() { Dashboard.Changed += Redraw; Dashboard.SlotFrameChanged += RedrawSlot; return true; }
    protected override bool OnUnload() { Dashboard.Changed -= Redraw; Dashboard.SlotFrameChanged -= RedrawSlot; return true; }
    private void RedrawSlot(int slot) => ActionImageChanged(slot.ToString());
    private void Redraw() { for (int i = 0; i < 9; i++) ActionImageChanged(i.ToString()); }
    protected override void RunCommand(string actionParameter)
    {
        // Recency can reorder Dashboard before the SDK asks for a new image.
        // Focus the identity used for this button's last completed render.
        if (int.TryParse(actionParameter, out int slot) && slot is >= 0 and < 9) Dashboard.Focus(_targets.Get(slot));
    }
    protected override string GetCommandDisplayName(string actionParameter, PluginImageSize imageSize)
        => TileFor(actionParameter) is { } tile ? PetDisplay.Labels(tile).Text : $"{Dashboard.PageText}\nEmpty";
    private static Tile? TileFor(string parameter) => int.TryParse(parameter, out int i) && i is >= 0 and < 9 ? Dashboard.Get(i) : null;
    protected override BitmapImage GetCommandImage(string actionParameter, PluginImageSize imageSize)
    {
        var tile = TileFor(actionParameter);
        BitmapImage Remember(BitmapImage image)
        {
            if (int.TryParse(actionParameter, out int slot) && slot is >= 0 and < 9)
                _targets.Displayed(slot, tile);
            return image;
        }
        try { var petImage = PetDisplay.Render(tile, imageSize); if (petImage is not null) return Remember(petImage); }
        catch (Exception ex) { PetDisplay.ReportRenderError(ex); }
        using var b = new BitmapBuilder(imageSize);
        var status = tile?.Status ?? "";
        b.Clear(PetDisplay.Background(status));
        string text = tile is null ? $"Page {Dashboard.PageText}\nEmpty" : PetDisplay.Labels(tile).Text;
        if (text.Length > 0) LabelRenderer.Draw(b, text, 0, b.Height, status);
        return Remember(b.ToImage());
    }
}

public sealed class NextPageCommand : PluginDynamicCommand
{
    public NextPageCommand() : base("Next agent page", "Show the next nine rows", "Agents") { }
    protected override bool OnLoad() { Dashboard.Changed += Redraw; return true; }
    protected override bool OnUnload() { Dashboard.Changed -= Redraw; return true; }
    private void Redraw() => ActionImageChanged();
    protected override void RunCommand(string actionParameter) => Dashboard.Move(1);
    protected override string GetCommandDisplayName(string p, PluginImageSize s)
        => $"Page {Dashboard.PageText}\n{Dashboard.FocusStatus}";
}

public sealed class AgentPageAdjustment : PluginDynamicAdjustment
{
    public AgentPageAdjustment() : base("Agent pages", "Rotate to browse nine agents per page", "Agents", false) { }
    protected override bool OnLoad() { Dashboard.Changed += Redraw; return true; }
    protected override bool OnUnload() { Dashboard.Changed -= Redraw; return true; }
    private void Redraw() => AdjustmentValueChanged();
    protected override void ApplyAdjustment(string actionParameter, int diff) => Dashboard.Move(diff);
    protected override string GetAdjustmentValue(string actionParameter) => Dashboard.PageText;
}
