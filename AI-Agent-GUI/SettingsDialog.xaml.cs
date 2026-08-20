using System.Collections.Generic;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace AIAgentGUI;

public sealed partial class SettingsDialog : ContentDialog
{
    private readonly GuiSettings _orig;

    /// <summary>用户点击"保存"后的设置结果 (取消时为 null)。</summary>
    public GuiSettings? Result { get; private set; }

    public SettingsDialog(GuiSettings settings, bool firstRun = false)
    {
        InitializeComponent();
        _orig = settings;
        Title = firstRun ? "首次使用 - 配置 API Key" : "⚙ 设置";

        foreach (var m in new[] { "deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner",
                                  "gpt-4o", "gpt-4o-mini", "claude-sonnet-4" })
            ModelBox.Items.Add(m);
        ModelBox.Text = settings.Model;

        BaseUrlBox.Text = settings.BaseUrl;
        ApiKeyBox.Password = settings.ApiKey;
        if (settings.ApiKey.Length > 0 && !firstRun)
            ApiKeyBox.PlaceholderText = "已保存密钥 (留空保持不变)";
        PortBox.Value = settings.Port;
        FontBox.Value = settings.FontSize;
        AccentBox.Text = settings.Accent;
        BgBox.Text = settings.Background;
    }

    private void ColorPreset_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is string tag && tag.Length > 2)
        {
            var hex = tag.Substring(1);
            if (tag[0] == 'A') AccentBox.Text = hex;
            else if (tag[0] == 'B') BgBox.Text = hex;
        }
    }

    private void OnPrimary(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        var model = ModelBox.Text.Trim();
        var baseUrl = BaseUrlBox.Text.Trim();
        if (string.IsNullOrEmpty(model) || string.IsNullOrEmpty(baseUrl))
        {
            args.Cancel = true;
            return;
        }
        var key = ApiKeyBox.Password.Trim();

        // 校验颜色, 非法则保留原值
        var accent = TryHex(AccentBox.Text.Trim()) ?? _orig.Accent;
        var background = TryHex(BgBox.Text.Trim()) ?? _orig.Background;

        Result = new GuiSettings
        {
            Model = model,
            BaseUrl = baseUrl,
            // 输入框留空时保留原密钥 (避免误清空)
            ApiKey = key.Length > 0 ? key : _orig.ApiKey,
            Port = (int)(PortBox.Value ?? 8000),
            FontSize = FontBox.Value ?? 14,
            Accent = accent,
            Background = background,
        };
    }

    private static string? TryHex(string s)
    {
        if (string.IsNullOrWhiteSpace(s)) return null;
        s = s.Trim().TrimStart('#');
        if (s.Length != 6) return null;
        try
        {
            UiColors.Hex(s);   // 解析失败会抛异常
            return "#" + s.ToUpperInvariant();
        }
        catch
        {
            return null;
        }
    }
}
