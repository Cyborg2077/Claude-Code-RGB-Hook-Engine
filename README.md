# Claude Code RGB Hook Engine

将 Claude Code 的工作状态实时映射为 RGB 灯光效果，让每一次 AI 交互都有独特的视觉反馈。

基于 [OpenRGB](https://openrgb.org/) 协议，支持 Claude Code Hook 与外部客户端平等控制，Last-Writer-Wins 策略。

## 核心特性

- **7 种内置灯效** — 静态、呼吸、脉冲、频闪、彩虹波浪、滑动光带、渐变脉冲
- **插件式灯效系统** — 继承 `BaseEffect` 即可自定义灯效，修改注册表即可启用
- **平等控制架构** — Claude Code Hook 与 OpenClaw / 外部 API 权限完全平等，后调用者生效
- **动态事件映射** — 运行时注册/修改事件→灯效规则，变更持久化到 `event_map.json`
- **线程安全渲染** — 独立 20 FPS 渲染线程，Lock 保护共享状态
- **热重载配置** — 无需重启即可更新事件映射

## 环境要求

- Python 3.8+
- [OpenRGB](https://openrgb.org/) 客户端（SDK Server 模式）
- 支持 Direct 模式的 RGB 设备

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 确保 OpenRGB 已启动并开启 SDK Server (默认端口 6742)

# 启动引擎
python script.py
```

服务运行在 `http://localhost:8080`，首次启动自动生成 `event_map.json` 配置文件。

## 灯效列表

| 灯效 | 注册名 | 说明 |
|------|--------|------|
| 静态纯色 | `static` | 固定颜色常亮 |
| 呼吸灯 | `breathing` | 正弦波平滑明暗过渡 |
| 脉冲灯 | `pulse` | 快速亮起、缓慢衰减 |
| 频闪灯 | `strobe` | 等间隔开关闪烁 |
| 彩虹波浪 | `rainbow_wave` | HSV 色相沿 LED 索引和时间双维度流动 |
| 滑动光带 | `marquee` | 2/3 区域点亮的光带从左向右循环移动，支持速度调节 |
| 渐变脉冲 | `gradient_pulse` | 在基础色与橙黄色之间正弦交替 |

## API 接口

### Hook 事件入口（Claude Code 使用）

```http
POST /api/v1/event
Content-Type: application/json

{"event": "SessionStart"}
```

### 直接控制入口（OpenClaw / 外部客户端）

```http
POST /api/v1/control
Content-Type: application/json

{"effect": "breathing", "color": [0, 255, 100]}
```

### 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/effects` | 查看所有可用灯效 |
| GET | `/api/v1/config/events` | 查看当前事件映射 |
| POST | `/api/v1/config/event` | 动态添加/修改事件映射 |
| POST | `/api/v1/config/reload` | 热重载配置文件 |

## Claude Code Hook 配置

### 配置文件位置

Claude Code 按优先级合并三个层级的设置：

| 层级 | 路径 | 作用范围 |
|------|------|---------|
| 用户级 | `~/.claude/settings.json` | 本机所有项目 |
| 项目级 | `<project>/.claude/settings.json` | 仅当前项目 |
| 本地级 | `<project>/.claude/settings.local.json` | 仅当前项目（不提交 Git） |

Windows 上 `~` 即 `C:\Users\<用户名>`。

### 配置 Hook 回调

在 `settings.json` 的 `hooks` 字段中为每个事件配置 HTTP 回调：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "curl -s -m 1 -X POST http://localhost:8080/api/v1/event -H 'Content-Type: application/json' -d '{\"event\":\"SessionStart\"}'"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "curl -s -m 1 -X POST http://localhost:8080/api/v1/event -H 'Content-Type: application/json' -d '{\"event\":\"UserPromptSubmit\"}'"
          }
        ]
      }
    ]
  }
}
```

- 每个事件是一个 matcher 数组，入口包含可选 `matcher` 字段（默认为空，匹配所有工具）
- `matcher` 可指定工具名如 `"Write|Edit"` 来限定触发范围
- 每个 matcher 的 `hooks` 数组中定义实际执行的 hook 动作
- `-s` 静默模式，`-m 1` 超时 1 秒，确保 hook 不阻塞 Claude Code 主流程
- 完整事件列表参考 [Hooks 官方文档](https://code.claude.com/docs/zh-TW/hooks-guide)

## 默认事件映射

| 事件 | 灯效 | 颜色 | 触发场景 |
|------|------|------|----------|
| SessionStart | rainbow_wave | [0, 255, 100] | 会话启动 |
| Stop | rainbow_wave | [0, 255, 100] | 会话结束 |
| UserPromptSubmit | marquee | [255, 140, 0] | 用户提交提示 |
| PreToolUse | marquee | [255, 140, 0] | 工具调用前 |
| PostToolUse | marquee | [255, 140, 0] | 工具调用后 |
| PermissionRequest | gradient_pulse | [255, 0, 0] | 权限请求 |
| PostToolUseFailure | gradient_pulse | [255, 0, 0] | 工具调用失败 |
| StopFailure | gradient_pulse | [255, 0, 0] | 停止失败 |
| SubagentStart | gradient_pulse | [255, 0, 0] | 子代理启动 |

## 架构

```
Claude Code Hook → /api/v1/event  → trigger_event() → apply_state()
                                                        ↓
OpenClaw / 外部   → /api/v1/control → apply_state() → RGB 渲染线程 (20 FPS)
```

- **主线程**：FastAPI 处理 HTTP 请求
- **渲染线程**：独立循环驱动灯效渲染
- **线程安全**：`threading.Lock` 保护 `effect_name` / `base_color`

## 自定义灯效

```python
from script import BaseEffect, EFFECT_REGISTRY

class MyEffect(BaseEffect):
    def render(self, phase, color, devices):
        # 实现灯效逻辑
        pass

EFFECT_REGISTRY["my_effect"] = MyEffect
```

## 开源协议

MIT License
