"""Build the active input sources from the input map.

Inspects the input-map keys: any "gpio:*" ids start a GpioSource on those pins,
and the presence of any "hid:*" ids starts a HidSource on the first gamepad.
"""

from __future__ import annotations

from .base import InputSource, merge


def build_sources(input_map: dict) -> list[InputSource]:
    sources: list[InputSource] = []

    gpio_pins = sorted({
        int(k.split(":", 1)[1]) for k in input_map if k.startswith("gpio:")
    })
    if gpio_pins:
        try:
            from .gpio import GpioSource
            sources.append(GpioSource(gpio_pins))
        except Exception as e:  # noqa: BLE001
            print(f"GPIO input unavailable: {e}")

    if any(k.startswith("hid:") for k in input_map):
        try:
            from .hid import HidSource
            sources.append(HidSource())
        except Exception as e:  # noqa: BLE001
            print(f"HID input unavailable: {e}")

    return sources


__all__ = ["InputSource", "merge", "build_sources"]
