using System;
using System.Globalization;
using System.IO;
using System.Text.Json;

namespace AIAgentGUI;

/// <summary>
/// GUI/网页版共享的自定义设置, 持久化到项目根目录 settings.json。
///
/// 键名兼容:
///   * 本程序写 camelCase (model / baseUrl / apiKey ...), 与 webui.py 落盘格式一致;
///   * 读取时忽略大小写, 因此旧版写入的 PascalCase (Model / BaseUrl / ApiKey) 仍可识别。
/// 旧版本因为写 PascalCase, 网页版读的是 snake_case, 两边设置实际上互不相认, 这里一并修好。
/// </summary>
public sealed class GuiSettings
{
    public string Model { get; set; } = "deepseek-v4-flash";
    public string BaseUrl { get; set; } = "https://api.deepseek.com";
    public string ApiKey { get; set; } = "";          // 留空则使用系统环境变量
    public int Port { get; set; } = 8000;
    public double FontSize { get; set; } = 14;
    public string Accent { get; set; } = "#4D9FFF";      // 主题色
    public string Background { get; set; } = "#0C1117";  // 背景色 (默认深色, 与桌面版深色外壳一致)

    private const string FileName = "settings.json";

    private static readonly JsonSerializerOptions ReadOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    private static readonly JsonSerializerOptions WriteOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    public static GuiSettings Load(string rootDir)
    {
        try
        {
            var path = Path.Combine(rootDir, FileName);
            if (!File.Exists(path))
            {
                // 兼容旧版本文件名
                var old = Path.Combine(rootDir, "gui_settings.json");
                if (File.Exists(old)) path = old;
                else return new GuiSettings();
            }
            var json = File.ReadAllText(path);
            var settings = JsonSerializer.Deserialize<GuiSettings>(json, ReadOptions) ?? new GuiSettings();
            settings.Normalize();
            return settings;
        }
        catch
        {
            return new GuiSettings();
        }
    }

    public void Save(string rootDir)
    {
        try
        {
            Normalize();
            var path = Path.Combine(rootDir, FileName);
            File.WriteAllText(path, JsonSerializer.Serialize(this, WriteOptions));
        }
        catch
        {
            // 保存失败不阻塞使用
        }
    }

    /// <summary>把文件里的可疑值收敛到可用范围，避免手改配置导致界面异常。</summary>
    public void Normalize()
    {
        Model = string.IsNullOrWhiteSpace(Model) ? "deepseek-v4-flash" : Model.Trim();
        BaseUrl = string.IsNullOrWhiteSpace(BaseUrl) ? "https://api.deepseek.com" : BaseUrl.Trim().TrimEnd('/');
        ApiKey = ApiKey?.Trim() ?? "";
        if (Port < 1024 || Port > 65535) Port = 8000;
        if (FontSize < 10 || FontSize > 26) FontSize = 14;
        Accent = NormalizeHex(Accent, "#4D9FFF");
        Background = NormalizeHex(Background, "#0C1117");
    }

    private static string NormalizeHex(string? value, string fallback)
    {
        var text = (value ?? "").Trim().TrimStart('#');
        if (text.Length != 6 ||
            !int.TryParse(text, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out _))
        {
            return fallback;
        }
        return "#" + text.ToUpperInvariant();
    }

    /// <summary>后端相关配置是否变化 (需要重启后端才生效)。主题色/字号即时生效, 不算。</summary>
    public bool BackendChanged(GuiSettings other) =>
        Model != other.Model || BaseUrl != other.BaseUrl ||
        ApiKey != other.ApiKey || Port != other.Port;
}
