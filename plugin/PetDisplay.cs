using System.Diagnostics;
using System.Text.Json;

namespace Loupedeck.CodexMxPlugin;

internal static class PetDisplay
{
    private static readonly object Gate = new();
    private static readonly Stopwatch Clock = Stopwatch.StartNew();
    private static DisplayOptions _options = new();
    private sealed record LoadedPet(string Id, PetManifest Manifest,
        Dictionary<string, BitmapImage> Images, long Pixels);
    private static Dictionary<string, LoadedPet> _pets = new();
    private static string _assetRoot = "";
    private static string _fingerprint = "";
    private static string _loadErrors = "";
    private static string _renderStatus = "";
    private static readonly HashSet<string> RenderedPets = new(StringComparer.Ordinal);
    private static bool _retry;
    private static readonly ChatNameIndex ChatNames = new();

    public static bool Refresh(string root)
    {
        string codexHome = Environment.GetEnvironmentVariable("CODEX_HOME") ??
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex");
        bool namesChanged = ChatNames.Refresh(Path.Combine(codexHome, "session_index.jsonl"));
        string fingerprint;
        DisplayOptions options;
        var pets = new Dictionary<string, LoadedPet>(StringComparer.Ordinal);
        var packErrors = new List<string>();
        string error = "";
        string configPath = "";
        string assetRoot = Path.GetFullPath(root);
        try
        {
            configPath = DisplayPaths.ReadLocation(root);
            var info = new FileInfo(configPath);
            if (info.Exists && info.Length > DisplayOptions.MaxBytes) throw new InvalidDataException("display.json exceeds 64 KiB");
            var raw = info.Exists ? File.ReadAllText(configPath) : "{\"schema_version\":1,\"mode\":\"text\"}";
            fingerprint = configPath + "\n" + raw;
            lock (Gate) if (fingerprint == _fingerprint && !_retry) return namesChanged;
            options = DisplayOptions.Parse(raw);
            if (options.Mode == "pet")
            {
                Dictionary<string, LoadedPet> previous;
                lock (Gate) previous = _assetRoot == assetRoot
                    ? _pets.Values.DistinctBy(p => p.Id).ToDictionary(p => p.Id)
                    : new();
                var loaded = new Dictionary<string, LoadedPet>(StringComparer.Ordinal);
                long availablePixels = PetPack.MaxLoadedPixels;
                foreach (string reference in PetSelection.References(options))
                {
                    try
                    {
                        string id = PetSelection.Resolve(root, reference);
                        if (!loaded.TryGetValue(id, out var pet))
                        {
                            if (!previous.TryGetValue(id, out pet))
                            {
                                var pack = PetPack.Load(root, id, availablePixels);
                                var images = pack.Frames.ToDictionary(p => p.Key, p => BitmapImage.FromArray(p.Value));
                                pet = new(pack.Id, pack.Manifest, images, pack.Pixels);
                            }
                            if (pet.Pixels > availablePixels)
                                throw new InvalidDataException("Selected pets exceed the loaded frame pixel limit");
                            availablePixels -= pet.Pixels;
                            loaded.Add(id, pet);
                        }
                        pets.Add(reference, pet);
                    }
                    catch (Exception ex) { packErrors.Add($"{reference}: {ex.Message}"); }
                }
            }
        }
        catch (Exception ex)
        {
            options = new();
            pets.Clear();
            fingerprint = "error:" + ex.GetType().Name + ":" + ex.Message;
            error = ex.Message;
        }
        bool changed;
        string errors = error + string.Join(" | ", packErrors);
        lock (Gate)
        {
            changed = fingerprint != _fingerprint || errors != _loadErrors;
            _fingerprint = fingerprint;
            _loadErrors = errors;
            _options = options;
            _pets = pets;
            _assetRoot = assetRoot;
            _retry = errors.Length > 0;
            if (changed) RenderedPets.Clear();
        }
        if (changed)
            try
            {
                Directory.CreateDirectory(root);
                if (!OperatingSystem.IsWindows())
                    File.SetUnixFileMode(root, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
                File.WriteAllText(Path.Combine(root, "display-status.txt"), error.Length == 0 ?
                    $"{DateTimeOffset.UtcNow:O} mode={options.Mode}; fps={options.Fps}; animate={options.Animate}; " +
                    $"show_name={options.ShowName}; show_location={options.ShowLocation}; " +
                    $"show_client={options.ShowClient}; show_status={options.ShowStatus}; use_chat_names={options.UseChatNames}; " +
                    $"chat_view={options.ChatView}; pet={options.Pet}; pet_rules={options.PetRules.Count}; " +
                    $"loaded_pets={string.Join(",", pets.Values.Select(p => p.Id).Distinct())}; " +
                    $"config_path={configPath}" +
                    (packErrors.Count == 0 ? "" : $"; pet_errors={string.Join(" | ", packErrors)}") :
                    $"{DateTimeOffset.UtcNow:O} Text fallback: {error}");
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { Trace.WriteLine(ex.Message); }
        return changed || namesChanged;
    }

    public static ButtonLabels Labels(Tile tile)
    {
        lock (Gate) return DisplayPlan.Labels(tile, _options, ChatNames.Names);
    }

    public static string ChatView { get { lock (Gate) return _options.ChatView; } }

    public static void Clear()
    {
        lock (Gate)
        {
            _pets.Clear(); RenderedPets.Clear(); _assetRoot = ""; _fingerprint = ""; _loadErrors = "";
            _renderStatus = ""; _retry = false; _options = new();
        }
        LabelRenderer.Clear();
    }

    public static void ReportRenderError(Exception error)
    {
        var message = $"Text fallback: {error.GetType().Name}: {error.Message}";
        ReportRenderStatus(message, message);
    }

    private static void ReportRenderStatus(string key, string message)
    {
        lock (Gate)
        {
            if (_renderStatus == key) return;
            _renderStatus = key;
        }
        try
        {
            var path = Path.Combine(Path.GetDirectoryName(Dashboard.StatePath)!, "render-status.txt");
            File.WriteAllText(path, $"{DateTimeOffset.UtcNow:O} {message}");
            if (!OperatingSystem.IsWindows())
                File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { Trace.WriteLine(ex.Message); }
    }

    private static (LoadedPet Pet, string File)? FrameFor(Tile tile)
    {
        string? reference = PetSelection.For(tile, _options);
        if (reference is null || !_pets.TryGetValue(reference, out var pet)) return null;
        var (state, moves) = DisplayPlan.Animation(tile.Status);
        var frames = pet.Manifest.Animations[state];
        string file = frames[DisplayPlan.Frame(frames.Length, _options.Fps, _options.Animate && moves, Clock.Elapsed.TotalSeconds)];
        return (pet, file);
    }

    public static string? FrameKey(Tile? tile)
    {
        if (tile is null) return null;
        lock (Gate)
        {
            var frame = FrameFor(tile);
            return frame is null ? null : $"{tile.Key}/{tile.Status}/{frame.Value.Pet.Id}/{frame.Value.File}";
        }
    }

    public static BitmapColor Background(string status) => status switch
    {
        "APPROVAL?" => new BitmapColor(110, 65, 0),
        "WORKING" or "TOOL" or "COMPACT" => new BitmapColor(0, 55, 95),
        "TURN STOP" or "STOPPED" => new BitmapColor(0, 70, 40),
        "EXIT ERROR" or "TURN ERROR" or "READ ERROR" => new BitmapColor(105, 20, 30),
        _ => new BitmapColor(32, 38, 48)
    };

    public static BitmapImage? Render(Tile? tile, PluginImageSize size)
    {
        if (tile is null) return null;
        lock (Gate)
        {
            var selected = FrameFor(tile);
            if (selected is null) return null;
            var (pet, file) = selected.Value;
            var manifest = pet.Manifest;
            var frame = pet.Images[file];
            using var b = new BitmapBuilder(size);
            var labels = DisplayPlan.Labels(tile, _options, ChatNames.Names);
            var (header, footer) = DisplayPlan.LabelHeights(labels, b.Height);
            double scale = Math.Min((b.Width-8.0)/manifest.FrameWidth, (b.Height-header-footer-4.0)/manifest.FrameHeight);
            int w = Math.Max(1, (int)(manifest.FrameWidth*scale)), h = Math.Max(1, (int)(manifest.FrameHeight*scale));
            var background = Background(tile.Status);
            b.Clear(background);
            if (header > 0) LabelRenderer.Draw(b, labels.Header, 0, header, tile.Status);
            b.DrawImage(frame, (b.Width-w)/2, header+(b.Height-header-footer-h)/2, w, h);
            if (footer > 0) LabelRenderer.Draw(b, labels.Footer, b.Height-footer, footer, tile.Status);
            var image = b.ToImage();
            RenderedPets.Add(pet.Id);
            string rendered = string.Join(",", RenderedPets.Order(StringComparer.Ordinal));
            ReportRenderStatus($"pets:{rendered}", $"Rendered pets {rendered}; image={b.Width}x{b.Height}");
            return image;
        }
    }
}
