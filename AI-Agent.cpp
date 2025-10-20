#include <cstdlib>
#include <iostream>
#include <string>
#include <filesystem>

int main() {
    // 获取虚拟环境下的 python.exe 路径
    std::string venv_python = std::filesystem::absolute(".venv\\Scripts\\python.exe").string();
    // 获取 chat.py 的绝对路径
    std::string script_path = std::filesystem::absolute("chat.py").string();

    // 构造命令：在新控制台窗口中运行
    std::string cmd = "start cmd /k \"" + venv_python + " " + script_path + "\"";

    // 执行命令
    std::system(cmd.c_str());

    return 0;
}