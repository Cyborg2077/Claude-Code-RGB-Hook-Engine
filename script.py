"""
Claude Code RGB Hook Engine (v4.0)
==================================
平等控制架构：Claude Code Hook 与 OpenClaw 均可独立控制灯效，
采用 Last-Writer-Wins 策略，无覆盖/锁定机制。

开源协议: MIT
"""

import colorsys
import json
import math
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Type

from fastapi import FastAPI, HTTPException
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor
from pydantic import BaseModel, Field


# ============================================================
# 1. 数据模型
# ============================================================

class EventReq(BaseModel):
    """Claude Code Hook 事件请求体"""
    event: str = Field(..., description="Hook 事件名称，如 SessionStart, PreToolUse")


class StateControlReq(BaseModel):
    """
    通用灯效控制请求体。
    Claude Code 和 OpenClaw 均使用此模型，权限完全平等。
    """
    effect: str = Field(..., description="灯效名称")
    color: List[int] = Field(..., min_length=3, max_length=3, description="RGB 颜色 [r, g, b]")


class EffectRegisterReq(BaseModel):
    """动态注册/更新事件映射的请求体"""
    event: str = Field(..., description="Hook 事件名称")
    effect: str = Field(..., description="灯效名称")
    color: List[int] = Field(..., min_length=3, max_length=3, description="RGB 颜色 [r, g, b]")


# ============================================================
# 2. 灯效插件系统
# ============================================================

class BaseEffect(ABC):
    """
    灯效基类。新增灯效只需继承此类并实现 render 方法，
    然后在 EFFECT_REGISTRY 中注册即可。
    """

    @abstractmethod
    def render(self, phase: float, color: List[int], devices: list) -> None:
        """
        渲染一帧灯效。
        Args:
            phase: 全局相位计数器，随时间递增
            color: 当前基础 RGB 颜色 [r, g, b]
            devices: OpenRGB 设备列表
        """
        ...


class StaticEffect(BaseEffect):
    """静态纯色"""
    def render(self, phase: float, color: List[int], devices: list) -> None:
        rgb = RGBColor(*color)
        for d in devices:
            d.set_color(rgb)


class BreathingEffect(BaseEffect):
    """呼吸灯：正弦波平滑明暗过渡"""
    def render(self, phase: float, color: List[int], devices: list) -> None:
        brightness = (math.sin(phase) + 1) / 2
        rgb = RGBColor(*(int(c * brightness) for c in color))
        for d in devices:
            d.set_color(rgb)


class PulseEffect(BaseEffect):
    """脉冲灯：快速亮起、缓慢衰减"""
    def render(self, phase: float, color: List[int], devices: list) -> None:
        val = max(0, math.sin(phase * 2))
        rgb = RGBColor(*(int(c * val) for c in color))
        for d in devices:
            d.set_color(rgb)


class StrobeEffect(BaseEffect):
    """频闪灯：等间隔开关闪烁"""
    def render(self, phase: float, color: List[int], devices: list) -> None:
        on = (phase * 2) % 2 > 1
        rgb = RGBColor(*color) if on else RGBColor(0, 0, 0)
        for d in devices:
            d.set_color(rgb)


class RainbowWaveEffect(BaseEffect):
    """彩虹波浪：HSV 色相沿 LED 索引和时间双维度流动"""
    def render(self, phase: float, color: List[int], devices: list) -> None:
        for d in devices:
            led_colors = []
            num_leds = len(d.colors)
            for i in range(num_leds):
                hue = (i / max(num_leds, 1) + phase * 0.1) % 1.0
                r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]
                led_colors.append(RGBColor(r, g, b))
            try:
                d.set_colors(led_colors)
            except Exception:
                d.set_color(led_colors[0] if led_colors else RGBColor(0, 0, 0))



class MarqueeEffect(BaseEffect):
    """滑动光带效果：2/3 区域点亮，并从左向右循环移动"""

    def __init__(self, speed: float = 5.0):
        """
        初始化速度参数
        :param speed: 速度倍率。1.0 是原速，2.0 是两倍速，0.5 是半速，以此类推。
        """
        super().__init__()
        self.speed = speed

    def render(self, phase: float, color: List[int], devices: list) -> None:
        for d in devices:
            num_leds = len(d.colors)
            if num_leds <= 0:
                continue

            # 初始化所有 LED 为黑色
            led_colors = [RGBColor(0, 0, 0) for _ in range(num_leds)]

            # 方案 A：如果 OpenRGB 驱动提供了标准的二维矩阵地图(matrix_map)
            if hasattr(d, 'matrix_map') and d.matrix_map and len(d.matrix_map[0]) > 0:
                matrix = d.matrix_map
                rows = len(matrix)
                cols = len(matrix[0])

                band_width = max(1, int(cols * 2 / 3))
                # 关键修改：乘以 self.speed 让 offset 递增得更快
                offset = int(phase * self.speed) % cols

                for r in range(rows):
                    for c in range(cols):
                        led_idx = matrix[r][c]
                        if led_idx is not None and 0 <= led_idx < num_leds:
                            relative_col = (c - offset) % cols
                            if relative_col < band_width:
                                led_colors[led_idx] = RGBColor(*color)

            # 方案 B：固定的 20 列物理切分
            else:
                cols = 20
                band_width = max(1, int(cols * 2 / 3))
                # 关键修改：乘以 self.speed 让 offset 递增得更快
                offset = int(phase * self.speed) % cols

                for i in range(num_leds):
                    col = i % cols
                    relative_col = (col - offset) % cols

                    if relative_col < band_width:
                        led_colors[i] = RGBColor(*color)

            # 下发颜色
            try:
                d.set_colors(led_colors)
            except Exception:
                d.set_color(RGBColor(*color))


class GradientPulseEffect(BaseEffect):
    """渐变脉冲：在基础色和黄色之间交替"""

    def render(self, phase: float, color: List[int], devices: list) -> None:
        # t 的范围依然是 0 ~ 1
        t = (math.sin(phase * 1.5) + 1) / 2

        # 定义目标颜色：黄色 (R=255, G=255, B=0)
        yellow = [255, 65, 0]

        # 使用 zip 同时遍历基础色(c)和黄色(y)的 RGB 通道进行线性插值
        blended = [int(c * t + y * (1 - t)) for c, y in zip(color, yellow)]

        rgb = RGBColor(*blended)
        for d in devices:
            d.set_color(rgb)


# ---- 灯效注册表 (新增灯效只需在此添加一行) ----
EFFECT_REGISTRY: Dict[str, Type[BaseEffect]] = {
    "static": StaticEffect,
    "breathing": BreathingEffect,
    "pulse": PulseEffect,
    "strobe": StrobeEffect,
    "rainbow_wave": RainbowWaveEffect,
    "marquee": MarqueeEffect,
    "gradient_pulse": GradientPulseEffect,
}


# ============================================================
# 3. 默认事件映射配置
# ============================================================

DEFAULT_EVENT_MAP: Dict[str, Dict] = {
    "SessionStart":       {"effect": "rainbow_wave",      "color": [0, 255, 100]},
    "Stop":               {"effect": "rainbow_wave",      "color": [0, 255, 100]},
    "UserPromptSubmit":   {"effect": "marquee",          "color": [255, 140, 0]},
    "PreToolUse":         {"effect": "marquee",      "color": [255, 140, 0]},
    "PostToolUse":        {"effect": "marquee",      "color": [255, 140, 0]},
    "PermissionRequest":  {"effect": "gradient_pulse",         "color": [255, 0, 0]},
    "PostToolUseFailure": {"effect": "gradient_pulse",         "color": [255, 0, 0]},
    "StopFailure":        {"effect": "gradient_pulse",         "color": [255, 0, 0]},
    "SubagentStart":      {"effect": "gradient_pulse", "color": [255, 0, 0]},
    "FileChanged":        {"effect": "pulse",          "color": [200, 200, 200]},
}



CONFIG_FILE = Path(__file__).parent / "event_map.json"


def load_event_map() -> Dict[str, Dict]:
    """优先从外部 JSON 加载事件映射，不存在则生成默认配置"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"[Config] 已从 {CONFIG_FILE} 加载 {len(data)} 条事件映射")
            return data
        except Exception as e:
            print(f"[Config] 加载配置文件失败，回退到默认配置: {e}")
    else:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_EVENT_MAP, f, indent=2, ensure_ascii=False)
        print(f"[Config] 已生成默认配置文件: {CONFIG_FILE}")
    return dict(DEFAULT_EVENT_MAP)


# ============================================================
# 4. RGB 渲染引擎
# ============================================================

class RGBEngine:
    """
    线程安全的 RGB 渲染引擎。
    采用 Last-Writer-Wins 策略：任何来源的控制请求都直接生效，
    不区分优先级，不设覆盖锁。
    """

    FRAME_INTERVAL = 0.05  # 20 FPS

    def __init__(self):
        self.lock = threading.Lock()
        self.running = True
        self.effect_name: str = "rainbow_wave"
        self.base_color: List[int] = [0, 255, 100]
        self._phase: float = 0

        self.event_map = load_event_map()
        self.devices = self._init_devices()

        self._render_thread = threading.Thread(target=self._render_loop, daemon=True)
        self._render_thread.start()

    @staticmethod
    def _init_devices() -> list:
        """连接 OpenRGB 并切换 Direct 模式"""
        try:
            client = OpenRGBClient()
            devices = client.devices
            for d in devices:
                direct_mode = next((m for m in d.modes if m.name == "Direct"), None)
                if direct_mode:
                    d.set_mode(direct_mode)
            print(f"[RGB] 已连接 {len(devices)} 个设备: {[d.name for d in devices]}")
            return devices
        except Exception as e:
            print(f"[RGB] OpenRGB 连接失败: {e}")
            return []

    def _render_loop(self):
        """独立渲染线程"""
        while self.running:
            self._phase += 0.1
            with self.lock:
                effect_name = self.effect_name
                color = self.base_color

            effect_cls = EFFECT_REGISTRY.get(effect_name)
            if effect_cls and self.devices:
                try:
                    effect_cls().render(self._phase, color, self.devices)
                except Exception as e:
                    print(f"[RGB] 渲染异常 ({effect_name}): {e}")

            time.sleep(self.FRAME_INTERVAL)

    def apply_state(self, effect: str, color: List[int], source: str) -> None:
        """
        统一状态写入入口。所有控制源（Hook / OpenClaw / API）均调用此方法。
        Last-Writer-Wins：直接覆盖当前状态，不做任何拦截。
        """
        if effect not in EFFECT_REGISTRY:
            raise ValueError(f"未知灯效: {effect}，可用: {list(EFFECT_REGISTRY.keys())}")
        with self.lock:
            self.effect_name = effect
            self.base_color = color
        print(f"[RGB] 状态已更新 | 来源: {source:<12} | 灯效: {effect:<16} | 颜色: RGB{tuple(color)}")

    def trigger_event(self, event_name: str) -> bool:
        """
        Claude Code Hook 事件触发入口。
        查找映射表并应用对应灯效，同时在日志中打印完整映射信息。
        """
        config = self.event_map.get(event_name)
        if not config:
            print(f"[Hook] ⚠️  未匹配事件: {event_name} (无对应灯效配置)")
            return False

        effect = config["effect"]
        color = config["color"]
        print(f"[Hook] 🎨 事件触发: {event_name:<24} → 灯效: {effect:<16} | 颜色: RGB{tuple(color)}")
        self.apply_state(effect, color, source="ClaudeHook")
        return True

    def reload_config(self) -> int:
        """热重载事件映射配置"""
        new_map = load_event_map()
        with self.lock:
            self.event_map = new_map
        return len(new_map)

    def update_event_mapping(self, event: str, effect: str, color: List[int]) -> None:
        """运行时修改事件映射并持久化"""
        if effect not in EFFECT_REGISTRY:
            raise ValueError(f"未知灯效: {effect}")
        entry = {"effect": effect, "color": color}
        with self.lock:
            self.event_map[event] = entry
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.event_map, f, indent=2, ensure_ascii=False)
        print(f"[Config] 事件映射已更新: {event} → {entry}")


# ============================================================
# 5. FastAPI 应用
# ============================================================

engine = RGBEngine()
app = FastAPI(
    title="Claude Code RGB Hook Engine",
    version="4.0.0",
    description="平等控制架构：Claude Code 与 OpenClaw 均可独立控制灯效，Last-Writer-Wins",
)


# ---- Claude Code Hook 接口 ----

@app.post("/api/v1/event", summary="接收 Claude Code Hook 事件")
def handle_event(req: EventReq):
    """
    Claude Code Hook 回调入口。
    根据事件映射表自动切换灯效，日志中会打印每个事件对应的灯效详情。
    """
    matched = engine.trigger_event(req.event)
    return {"status": "matched" if matched else "unmapped", "event": req.event}


# ---- OpenClaw / 通用控制接口 ----

@app.post("/api/v1/control", summary="[OpenClaw] 直接控制灯效")
def control_state(req: StateControlReq):
    """
    OpenClaw 或任何外部客户端的直接控制入口。
    与 Claude Hook 权限完全平等，后调用者生效。
    """
    try:
        engine.apply_state(req.effect, req.color, source="OpenClaw")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "applied", "effect": req.effect, "color": req.color}


# ---- 配置管理接口 ----

@app.post("/api/v1/config/event", summary="动态添加/修改事件映射")
def update_event_mapping(req: EffectRegisterReq):
    """运行时注册或修改事件→灯效映射，变更持久化到 event_map.json"""
    try:
        engine.update_event_mapping(req.event, req.effect, req.color)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "updated", "event": req.event}


@app.post("/api/v1/config/reload", summary="热重载事件映射配置")
def reload_config():
    """重新读取 event_map.json"""
    count = engine.reload_config()
    return {"status": "reloaded", "rules_count": count}


@app.get("/api/v1/config/events", summary="查看当前所有事件映射")
def get_event_map():
    return engine.event_map


@app.get("/api/v1/effects", summary="查看所有可用灯效")
def list_effects():
    return {"effects": list(EFFECT_REGISTRY.keys())}


# ============================================================
# 6. 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)