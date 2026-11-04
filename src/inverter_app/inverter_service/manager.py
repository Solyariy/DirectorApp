from dataclasses import dataclass

from pysolarmanv5 import PySolarmanV5

from src.inverter_app.inverter_service.settings import (
    INVERTER_LOGGER_IP,
    INVERTER_LOGGER_SERIAL,
)


@dataclass
class InverterStats:
    solar_power_w: int
    load_power_w: int
    grid_power_w: int
    battery_power_w: int
    battery_charge_pct: int
    battery_voltage_v: float
    grid_voltage_v: float
    pv1_voltage_v: float
    pv1_current_a: float
    pv1_power_w: int
    pv2_voltage_v: float
    pv2_current_a: float
    pv2_power_w: int
    battery_max_charge_current_a: int


class InverterManager:
    BASE = 150
    COUNT = 61  # 150..210
    PV_BASE = 109
    PV_COUNT = 4  # 109..112: PV1 V/I, PV2 V/I

    def __enter__(self):
        self.inv = PySolarmanV5(
            INVERTER_LOGGER_IP,
            INVERTER_LOGGER_SERIAL,
            port=8899,
            socket_timeout=10,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.inv.disconnect()

    @staticmethod
    def _s16(v):  # unsigned 16-bit -> signed
        return v - 65536 if v > 32767 else v

    @staticmethod
    def _reg(response, base, addr):
        return response[addr - base]

    def _format_registers_response(
        self,
        response,
        pv_response,
    ) -> InverterStats:
        def reg(addr):
            return self._reg(
                response,
                self.BASE,
                addr,
            )

        def pv(addr):
            return self._reg(
                pv_response,
                self.PV_BASE,
                addr,
            )

        return InverterStats(
            solar_power_w=reg(186) + reg(187),
            load_power_w=reg(178),
            grid_power_w=self._s16(reg(169)),
            # Positive = discharging, negative = charging.
            battery_power_w=self._s16(reg(190)),
            battery_charge_pct=reg(184),
            battery_voltage_v=reg(183) / 100,
            grid_voltage_v=reg(150) / 10,
            pv1_voltage_v=pv(109) / 10,
            pv1_current_a=pv(110) / 10,
            pv1_power_w=reg(186),
            pv2_voltage_v=pv(111) / 10,
            pv2_current_a=pv(112) / 10,
            pv2_power_w=reg(187),
            battery_max_charge_current_a=reg(210),
        )

    def read_registers(self) -> InverterStats:
        response = self.inv.read_holding_registers(
            register_addr=self.BASE, quantity=self.COUNT
        )
        pv_response = self.inv.read_holding_registers(
            register_addr=self.PV_BASE, quantity=self.PV_COUNT
        )
        formatted = self._format_registers_response(response, pv_response)
        return formatted


if __name__ == "__main__":
    with InverterManager() as inv:
        print(inv.read_registers())
