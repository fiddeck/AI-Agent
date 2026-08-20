using System;
using Windows.UI;
using Microsoft.UI.Xaml.Media;

namespace AIAgentGUI;

/// <summary>
/// 主题配色。由 背景色 + 主题色 推导整套颜色:
/// 背景色亮度高 -> 浅色主题 (白底深字); 亮度低 -> 深色主题 (黑底浅字)。
/// 算法与网页版 (webui.py) 保持一致。
/// </summary>
public static class UiColors
{
    public static bool IsDarkTheme = true;

    public static Color Background = Hex("#FFFFFF");
    public static Color Panel = Hex("#F0F2F5");
    public static Color Panel2 = Hex("#FFFFFF");
    public static Color Border = Hex("#D0D7DE");
    public static Color Text = Hex("#1F2328");
    public static Color Muted = Hex("#57606A");
    public static Color CodeBg = Hex("#F6F8FA");
    public static Color CodeText = Hex("#24292F");
    public static Color Accent = Hex("#4D9FFF");
    public static Color AccentDark = Hex("#1F6FEB");
    public static Color UserBubble = Hex("#DDEBFF");
    public static Color BadgeBg = Hex("#DCEBFA");

    public static readonly Color Danger = Hex("#F85149");
    public static readonly Color Green = Hex("#3FB950");

    static UiColors()
    {
        Apply("#4D9FFF", "#FFFFFF");
    }

    /// <summary>按 主题色 + 背景色 重算整套配色。</summary>
    public static void Apply(string accentHex, string bgHex)
    {
        try
        {
            var accent = Hex(accentHex ?? "#4D9FFF");
            var bg = Hex(bgHex ?? "#FFFFFF");
            Accent = accent;
            Background = bg;
            IsDarkTheme = Luminance(bg) < 128;
            AccentDark = Darken(accent, 0.62f);
            UserBubble = Blend(accent, bg, 0.22);
            BadgeBg = Blend(accent, bg, 0.12);

            if (IsDarkTheme)
            {
                Panel = Blend(bg, Hex("#12171E"), 0.65);
                Panel2 = Blend(bg, Hex("#161D26"), 0.8);
                Border = Hex("#232C37");
                Text = Hex("#E6EDF3");
                Muted = Hex("#8B98A5");
                CodeBg = Blend(bg, Hex("#0D1117"), 0.85);
                CodeText = Hex("#C9D4DE");
            }
            else
            {
                Panel = Blend(bg, Hex("#F6F8FA"), 0.65);
                Panel2 = Blend(bg, Hex("#FFFFFF"), 0.8);
                Border = Hex("#D0D7DE");
                Text = Hex("#1F2328");
                Muted = Hex("#57606A");
                CodeBg = Blend(bg, Hex("#F6F8FA"), 0.85);
                CodeText = Hex("#24292F");
            }
        }
        catch
        {
            // 非法颜色保持默认
        }
    }

    private static double Luminance(Color c) => 0.2126 * c.R + 0.7152 * c.G + 0.0722 * c.B;

    private static Color Darken(Color c, float factor)
    {
        return Color.FromArgb(255,
            (byte)Math.Min(255, c.R * factor),
            (byte)Math.Min(255, c.G * factor),
            (byte)Math.Min(255, c.B * factor));
    }

    private static Color Blend(Color c1, Color c2, double alpha)
    {
        return Color.FromArgb(255,
            (byte)Math.Round(c1.R * alpha + c2.R * (1 - alpha)),
            (byte)Math.Round(c1.G * alpha + c2.G * (1 - alpha)),
            (byte)Math.Round(c1.B * alpha + c2.B * (1 - alpha)));
    }

    public static Color Hex(string h)
    {
        h = h.TrimStart('#');
        return Color.FromArgb(
            255,
            byte.Parse(h.Substring(0, 2), System.Globalization.NumberStyles.HexNumber),
            byte.Parse(h.Substring(2, 2), System.Globalization.NumberStyles.HexNumber),
            byte.Parse(h.Substring(4, 2), System.Globalization.NumberStyles.HexNumber));
    }

    public static string ToHex(Color c) => $"#{c.R:X2}{c.G:X2}{c.B:X2}";

    public static SolidColorBrush Brush(Color c) => new(c);
}
