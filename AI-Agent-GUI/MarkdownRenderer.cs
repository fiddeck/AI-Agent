using System.Collections.Generic;
using System.Linq;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml.Documents;

namespace AIAgentGUI;

/// <summary>
/// 极简 Markdown 渲染: 代码块 + 段落 + **粗体** + `行内代码`。
/// 足以覆盖 AI 回复的常见格式; 复杂表格等暂不处理。
/// </summary>
public static class MarkdownRenderer
{
    /// <summary>把整段文本拆成 代码块 / 普通段落 两类。</summary>
    public static List<MarkdownBlock> SplitBlocks(string text)
    {
        var blocks = new List<MarkdownBlock>();

        void AddText(string s)
        {
            if (string.IsNullOrWhiteSpace(s)) return;
            // 按空行拆成段落
            foreach (var para in s.Split('\n'))
            {
                var t = para.TrimEnd('\r');
                if (!string.IsNullOrWhiteSpace(t))
                    blocks.Add(new MarkdownBlock { IsCode = false, Text = t.Trim() });
            }
        }

        int pos = 0;
        while (pos < text.Length)
        {
            int start = text.IndexOf("```", pos);
            if (start < 0)
            {
                AddText(text.Substring(pos));
                break;
            }
            if (start > pos)
                AddText(text.Substring(pos, start - pos));

            int end = text.IndexOf("```", start + 3);
            if (end < 0)
            {
                AddText(text.Substring(start));
                break;
            }
            var code = text.Substring(start + 3, end - start - 3);
            code = TrimLanguageLine(code);           // 去掉首行语言标记
            blocks.Add(new MarkdownBlock { IsCode = true, Text = code.Trim('\n', '\r') });
            pos = end + 3;
        }
        return blocks;
    }

    private static string TrimLanguageLine(string code)
    {
        var idx = code.IndexOf('\n');
        if (idx < 0) return code;
        var first = code.Substring(0, idx).Trim();
        // 首行是常见语言标记时去掉
        if (first.Length > 0 && first.Length < 20 && first.All(c => char.IsLetterOrDigit(c) || c is '#' or '+' or '-'))
            return code.Substring(idx + 1);
        return code;
    }

    /// <summary>把段落文本转为 Inline 集合 (支持 **粗体** 与 `行内代码`)。</summary>
    public static IList<Inline> BuildInlines(string text)
    {
        var inlines = new List<Inline>();
        var segs = SplitStyled(text);
        foreach (var (kind, content) in segs)
        {
            switch (kind)
            {
                case "code":
                    inlines.Add(new Run
                    {
                        Text = content,
                        FontFamily = new Microsoft.UI.Xaml.Media.FontFamily("Consolas"),
                        Foreground = UiColors.Brush(UiColors.Text),
                        FontSize = 12.5,
                    });
                    break;
                case "bold":
                    inlines.Add(new Run { Text = content, FontWeight = FontWeights.Bold, Foreground = UiColors.Brush(UiColors.Text) });
                    break;
                default:
                    inlines.Add(new Run { Text = content, Foreground = UiColors.Brush(UiColors.Text) });
                    break;
            }
        }
        return inlines;
    }

    private static List<(string Kind, string Text)> SplitStyled(string text)
    {
        var result = new List<(string, string)>();
        string buf = "";
        int i = 0;
        while (i < text.Length)
        {
            // 行内代码
            if (text[i] == '`')
            {
                int end = text.IndexOf('`', i + 1);
                if (end > i)
                {
                    if (buf.Length > 0) { result.Add(("plain", buf)); buf = ""; }
                    result.Add(("code", text.Substring(i + 1, end - i - 1)));
                    i = end + 1;
                    continue;
                }
            }
            // 粗体 **x**
            if (i + 1 < text.Length && text[i] == '*' && text[i + 1] == '*')
            {
                int end = text.IndexOf("**", i + 2);
                if (end > i)
                {
                    if (buf.Length > 0) { result.Add(("plain", buf)); buf = ""; }
                    result.Add(("bold", text.Substring(i + 2, end - i - 2)));
                    i = end + 2;
                    continue;
                }
            }
            buf += text[i];
            i++;
        }
        if (buf.Length > 0) result.Add(("plain", buf));
        return result;
    }
}
