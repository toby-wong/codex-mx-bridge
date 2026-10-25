using System.Globalization;
using System.Text;
using System.Text.Json;
using Loupedeck.CodexMxPlugin;

internal static class LabelLayoutTests
{
    public static int Run()
    {
        int count = 0;
        void Check(bool condition, string message)
        {
            if (!condition) throw new Exception(message);
            count++;
        }
        int Measure(string value, int size) => value.EnumerateRunes().Sum(r =>
            Rune.GetUnicodeCategory(r) == UnicodeCategory.NonSpacingMark ? 0 :
            r.Value is 'W' or 'M' or >= 0x1000 ? size : (size + 1) / 2);
        void Bounds(FittedLabel result, int width, int height)
        {
            Check(result.Lines.All(line => Measure(line, result.FontSize) <= width),
                  "every rendered line fits its horizontal space");
            Check(result.Lines.Length * result.LineHeight <= height,
                  "every rendered line fits its vertical space");
        }

        var shortName = LabelLayout.Fit("Codex · local\ncodex-mx-bridge", 108, 36, Measure);
        Check(shortName.Text == "Codex · local\ncodex-mx-bridge" && shortName.FontSize == 12,
              "short headers retain the preferred readable size");
        Bounds(shortName, 108, 36);
        var installed = LabelLayout.Fit("Codex · local\nInstall codex-mx-bridge", 108, 36, Measure);
        Check(installed.Text.Replace("\n", " ").Contains("Install codex-mx-bridge") &&
              !installed.Text.Contains('…'), "the user's title fits without clipping or truncation");
        Bounds(installed, 108, 36);
        var words = LabelLayout.Fit("A long project-name/with-separators", 72, 120, Measure);
        Check(string.Concat(words.Lines).Replace(" ", "") == "Alongproject-name/with-separators",
              "wrapping preserves long names and separators");
        Bounds(words, 72, 120);
        var wide = LabelLayout.Fit(new string('W', 80), 108, 36, Measure);
        Check(wide.Text.EndsWith('…'), "overlong names end with an explicit ellipsis");
        Bounds(wide, 108, 36);
        var unicode = LabelLayout.Fit("猫😺e\u0301猫😺e\u0301", 20, 120, Measure);
        Check(string.Concat(unicode.Lines) == "猫😺e\u0301猫😺e\u0301" &&
              unicode.Lines.All(line => !line.StartsWith('\u0301')),
              "wrapping preserves surrogate pairs and combining marks");
        Bounds(unicode, 20, 120);
        foreach (var (width, height) in new[] { (4, 8), (1, 2), (32, 16), (108, 17) })
            Bounds(LabelLayout.Fit("APPROVAL?", width, height, Measure), width, height);
        Check(LabelLayout.Fit("", 108, 36, Measure).Lines.Length == 0, "hidden labels remain empty");
        var state = ViewModel.Parse("""
            {"schema_version":1,"rows":[{"key":"long","name":"a-long-project-name-that-must-survive","valid_until":100}],"remotes":{}}
            """);
        Check(ViewModel.Tiles(state, 1)[0].Name == "a-long-project-name-that-must-survive",
              "project names reach the layout without the old 18-character truncation");
        string prefix = new('a', 79);
        foreach (string ending in new[] { "😺", "e\u0301", "👩‍💻" })
        {
            string name = prefix + ending;
            Check(ViewModel.Short(name, 80) == prefix, "the name cap never splits a Unicode grapheme");
            string entry = JsonSerializer.Serialize(new { id = "unicode", thread_name = name });
            Check(ChatNameIndex.Parse(entry)["unicode"] == prefix, "saved chat names use the same safe cap");
        }
        Check(ViewModel.Short(new string('a', 78) + "😺tail", 80) == new string('a', 78) + "😺",
              "a complete emoji fitting exactly at the boundary is retained");
        Check(ViewModel.Short("abc", 0) == "" && ViewModel.Short("abc", -1) == "",
              "empty bounds retain the prior empty-name behavior");
        return count;
    }
}
