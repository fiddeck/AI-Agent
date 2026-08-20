namespace AIAgentGUI;

/// <summary>侧边栏会话信息。</summary>
public sealed record SessionInfo(string Sid, string Title);

/// <summary>历史消息 (仅 user / assistant 文本)。</summary>
public sealed record HistoryMessage(string Role, string Content);

/// <summary>Markdown 内容块: 代码块或普通段落。</summary>
public sealed class MarkdownBlock
{
    public bool IsCode { get; init; }
    public string Text { get; init; } = "";
}
