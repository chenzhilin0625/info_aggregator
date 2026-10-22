# AI信息自动抓取分析系统

从关注流抓取内容，用 DeepSeek API 提取相关信息，生成结构化日报并通过邮件推送。

## 目录结构

```
ai-info-analyst/
├── main.py                     # 程序入口
├── config/config.yaml           # 所有配置（Cookie、API Key、邮件等）
├── src/
│   ├── crawler/                 # 抓取（feed + 关注用户）
│   ├── analyzer/                # AI 分类 + 摘要 + 综合
│   ├── reporter/                # HTML/MD 报告生成 + 邮件发送
│   ├── storage/                 # SQLite 去重 + 运行历史
│   └── utils/                   # 日志、重试
├── templates/                   # Jinja2 模板
├── scripts/
│   ├── run_daily.bat            # 定时任务入口（Task Scheduler 调用）
│   └── run_now.bat              # 手动执行（双击即可，有交互提示）
├── output/
│   ├── reports/                 # 生成的报告
│   └── logs/                    # 运行日志
└── README.md
```

## 快速开始

### 手动运行（当天内容）

```powershell
cd D:\ai-info-analyst
.venv\Scripts\python.exe main.py
```

### 手动运行（指定日期）

```powershell
.venv\Scripts\python.exe main.py --date 2026-06-03
```

### 双击运行

直接双击 `scripts/run_now.bat`，按提示操作。

## 定时任务操作

### 创建定时任务（每天 23:30 执行）

```powershell
schtasks /create /tn "ai-info-analyst" /tr "D:\ai-info-analyst\scripts\run_daily.bat" /sc daily /st 23:30 /f
```

### 查看任务状态

```powershell
schtasks /query /tn "ai-info-analyst" /v /fo list
```

只看关键信息：

```powershell
schtasks /query /tn "ai-info-analyst" /v /fo list | findstr "Status Enabled Last"
```

### 禁用任务（暂停，保留配置）

```powershell
schtasks /change /tn "ai-info-analyst" /disable
```

### 启用任务（恢复）

```powershell
schtasks /change /tn "ai-info-analyst" /enable
```

### 手动触发一次

```powershell
schtasks /run /tn "ai-info-analyst"
```

### 修改执行时间

```powershell
schtasks /change /tn "ai-info-analyst" /st 08:00
```

### 彻底删除

```powershell
schtasks /delete /tn "ai-info-analyst" /f
```

## 日志查看

运行日志按日期存放在 `output/logs/run_YYYYMMDD.log`。

```powershell
# 看最新日志
Get-Content output\logs\run_20260604.log -Tail 30 -Encoding utf8

# 看 stderr 错误（定时任务环境下的异常）
Get-Content output\logs\task_stderr.log -ErrorAction SilentlyContinue
```

## 常见问题

### 定时任务没跑

1. 先确认任务是否存在：`schtasks /query /tn "ai-info-analyst"`
2. 看 **Enabled** 是否为 `True`，**Status** 是否为 `Ready`
3. 看 **Last Result**：
   - `0` → 正常
   - `255` → bat 脚本语法错误或文件找不到
   - `-1073741510` (0xC000013A) → Python 进程启动失败（DLL 缺失或环境问题）
   - `267009` → 正在运行中
4. 检查日志 `output/logs/run_YYYYMMDD.log` 有无内容

### bat 脚本注意事项

- 必须用 **纯 ASCII** 编写，不能有中文注释。`cmd.exe` 在中文 Windows 上以 GBK 编码解析 bat 文件
- 必须在 `cd /d` 之前或之后设置 `PATH`，确保 `python311.dll` 可被找到
- Task Scheduler 的工作目录与用户 session 不同，`cd /d` 是必须的

### 多 Python 环境

系统上同时存在 Python 3.11 和 3.14 不会影响定时任务，因为 bat 脚本使用显式路径 `.venv\Scripts\python.exe`，不依赖 PATH 中的 python。
