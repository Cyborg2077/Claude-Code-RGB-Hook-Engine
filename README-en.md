# Claude Code RGB Hook Engine

Map Claude Code's working state to RGB lighting effects in real time, giving every AI interaction a unique visual feedback.

Built on the [OpenRGB](https://openrgb.org/) protocol. Supports equal-priority control between Claude Code Hooks and external clients via a Last-Writer-Wins strategy.

## Key Features

- **7 built-in effects** — Static, Breathing, Pulse, Strobe, Rainbow Wave, Marquee, Gradient Pulse
- **Plugin-based effects system** — extend `BaseEffect` to create custom effects, enable with one registry entry
- **Equal control architecture** — Claude Code Hooks and OpenClaw / external APIs share the same priority; last caller wins
- **Dynamic event mapping** — register or modify event→effect rules at runtime, persisted to `event_map.json`
- **Thread-safe rendering** — independent 20 FPS render loop with Lock-protected shared state
- **Hot reload** — update event mappings without restarting the service

## Requirements

- Python 3.8+
- [OpenRGB](https://openrgb.org/) client (SDK Server mode)
- RGB devices supporting Direct mode

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Ensure OpenRGB is running with SDK Server enabled (default port 6742)

# Start the engine
python script.py
```

The service runs at `http://localhost:8080`. On first launch, `event_map.json` is auto-generated.

## Effects

| Effect | ID | Description |
|--------|-----|-------------|
| Static | `static` | Solid color |
| Breathing | `breathing` | Sine-wave brightness fading |
| Pulse | `pulse` | Quick attack, slow decay |
| Strobe | `strobe` | Regular on/off flashing |
| Rainbow Wave | `rainbow_wave` | HSV hue flowing across LED index and time |
| Marquee | `marquee` | 2/3-width light band scrolling left to right, speed-adjustable |
| Gradient Pulse | `gradient_pulse` | Sine-blend between base color and orange-yellow |

## API Endpoints

### Hook event (for Claude Code)

```http
POST /api/v1/event
Content-Type: application/json

{"event": "SessionStart"}
```

### Direct control (for OpenClaw / external clients)

```http
POST /api/v1/control
Content-Type: application/json

{"effect": "breathing", "color": [0, 255, 100]}
```

### Configuration management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/effects` | List available effects |
| GET | `/api/v1/config/events` | View current event mappings |
| POST | `/api/v1/config/event` | Add or modify an event mapping |
| POST | `/api/v1/config/reload` | Hot reload config from `event_map.json` |

## Claude Code Hook Configuration

### Settings File Locations

Claude Code merges three tiers of configuration by priority:

| Tier | Path | Scope |
|------|------|-------|
| User | `~/.claude/settings.json` | All projects on this machine |
| Project | `<project>/.claude/settings.json` | Current project only |
| Local | `<project>/.claude/settings.local.json` | Current project only (not committed) |

On Windows, `~` resolves to `C:\Users\<username>`.

### Configuring Hook Callbacks

Add HTTP callbacks for each event in the `hooks` field of `settings.json`:

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

- Each event maps to an array of matcher objects, each with an optional `matcher` field (empty = match all tools)
- Set `matcher` to a tool name like `"Write|Edit"` to limit trigger scope
- The `hooks` array inside each matcher defines the actual hook actions
- `-s` silent mode + `-m 1` 1-second timeout ensures hooks don't block Claude Code
- See the [Hooks documentation](https://code.claude.com/docs/en/hooks-guide) for the full list of supported events

## Default Event Mappings

| Event | Effect | Color | Trigger |
|-------|--------|-------|---------|
| SessionStart | rainbow_wave | [0, 255, 100] | Session started |
| Stop | rainbow_wave | [0, 255, 100] | Session ended |
| UserPromptSubmit | marquee | [255, 140, 0] | User submitted prompt |
| PreToolUse | marquee | [255, 140, 0] | Before tool execution |
| PostToolUse | marquee | [255, 140, 0] | After tool execution |
| PermissionRequest | gradient_pulse | [255, 0, 0] | Permission requested |
| PostToolUseFailure | gradient_pulse | [255, 0, 0] | Tool execution failed |
| StopFailure | gradient_pulse | [255, 0, 0] | Stop failed |
| SubagentStart | gradient_pulse | [255, 0, 0] | Sub-agent started |
| FileChanged | pulse | [200, 200, 200] | File changed |

## Architecture

```
Claude Code Hook → /api/v1/event  → trigger_event() → apply_state()
                                                       ↓
OpenClaw / External → /api/v1/control → apply_state() → RGB Render Thread (20 FPS)
```

- **Main thread**: FastAPI handles HTTP requests
- **Render thread**: Independent loop drives effect rendering
- **Thread safety**: `threading.Lock` guards `effect_name` / `base_color`

## Custom Effects

```python
from script import BaseEffect, EFFECT_REGISTRY

class MyEffect(BaseEffect):
    def render(self, phase, color, devices):
        # Implement your effect logic here
        pass

EFFECT_REGISTRY["my_effect"] = MyEffect
```

## License

MIT License
