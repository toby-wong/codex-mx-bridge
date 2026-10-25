using System.Globalization;
using System.Text;

namespace Loupedeck.CodexMxPlugin;

public sealed record FittedLabel(string[] Lines, int FontSize, int LineHeight)
{
    public string Text => string.Join("\n", Lines);
}

public static class LabelLayout
{
    public static FittedLabel Fit(string text, int width, int height, Func<string, int, int> measure)
    {
        if (string.IsNullOrWhiteSpace(text) || width <= 0 || height < 3)
            return new(Array.Empty<string>(), 0, 0);
        int maximum = Math.Min(12, Math.Max(1, height - 2));
        int minimum = Math.Min(8, maximum);
        for (int size = maximum; size >= minimum; size--)
        {
            int lineHeight = size + 2;
            int capacity = Math.Max(1, height / lineHeight);
            var lines = Wrap(text, width, size, measure);
            if (lines.Count <= capacity)
                return new(lines.ToArray(), size, lineHeight);
            if (size == minimum)
            {
                var visible = lines.Take(capacity).ToArray();
                visible[^1] = Ellipsis(visible[^1], width, size, measure);
                return new(visible, size, lineHeight);
            }
        }
        throw new InvalidOperationException("No label layout selected");
    }

    private static List<string> Wrap(string text, int width, int size, Func<string, int, int> measure)
    {
        var lines = new List<string>();
        foreach (var paragraph in text.Split('\n', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries))
        {
            string line = "";
            foreach (var word in paragraph.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
            {
                string candidate = line.Length == 0 ? word : line + " " + word;
                if (measure(candidate, size) <= width) { line = candidate; continue; }
                if (line.Length > 0) { lines.Add(line); line = ""; }
                // Break a long project name at a grapheme boundary, preferring
                // hyphens/slashes when possible. Never split a surrogate pair.
                foreach (string part in Parts(word))
                {
                    if (line.Length > 0 && measure(line + part, size) > width)
                    {
                        lines.Add(line);
                        line = "";
                    }
                    if (measure(part, size) <= width) { line += part; continue; }
                    foreach (string element in Elements(part))
                    {
                        if (line.Length > 0 && measure(line + element, size) > width)
                        {
                            lines.Add(line);
                            line = "";
                        }
                        line += measure(element, size) <= width ? element :
                            measure("…", size) <= width ? "…" : "";
                    }
                }
            }
            if (line.Length > 0) lines.Add(line);
        }
        return lines;
    }

    private static IEnumerable<string> Parts(string text)
    {
        var part = new StringBuilder();
        foreach (string element in Elements(text))
        {
            part.Append(element);
            if (element is "-" or "_" or "/")
            {
                yield return part.ToString();
                part.Clear();
            }
        }
        if (part.Length > 0) yield return part.ToString();
    }

    private static IEnumerable<string> Elements(string text)
    {
        var elements = StringInfo.GetTextElementEnumerator(text);
        while (elements.MoveNext()) yield return elements.GetTextElement();
    }

    private static string Ellipsis(string text, int width, int size, Func<string, int, int> measure)
    {
        var elements = Elements(text.TrimEnd()).ToList();
        while (elements.Count > 0 && measure(string.Concat(elements) + "…", size) > width)
            elements.RemoveAt(elements.Count - 1);
        return measure("…", size) <= width ? string.Concat(elements).TrimEnd() + "…" : "";
    }
}
