from dataclasses import dataclass

from pysolarmanv5 import PySolarmanV5

from src.inverter_service.settings import INVERTER_LOGGER_IP, INVERTER_LOGGER_SERIAL


@dataclass
class InverterStats:
    pv_w: int
    load_w: int
    grid_w: int
    batt_w: int
    soc_p: float
    batt_v: float
    grid_v: float


class InverterManager:
    BASE = 150
    COUNT = 45

    def __enter__(self):
        self.inv = PySolarmanV5(
            INVERTER_LOGGER_IP,
            INVERTER_LOGGER_SERIAL,
            port=8899,
            socket_timeout=10
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.inv.disconnect()

    @staticmethod
    def _s16(v):  # unsigned 16-bit -> signed
        return v - 65536 if v > 32767 else v

    def _reg(self, response, addr):
        return response[addr - self.BASE]

    def _format_registers_response(self, response) -> InverterStats:
        reg = lambda addr: self._reg(response=response, addr=addr)
        return InverterStats(
            pv_w=reg(186) + reg(187),
            load_w=reg(178),
            grid_w=self._s16(reg(169)),
            batt_w=self._s16(reg(190)),
            soc_p=reg(184),
            batt_v=reg(183) / 100,
            grid_v=reg(150) / 10,
        )

    def read_registers(self) -> InverterStats:
        response = self.inv.read_holding_registers(register_addr=self.BASE, quantity=self.COUNT)
        formatted = self._format_registers_response(response)
        return formatted


if __name__ == '__main__':
    with InverterManager() as inv:
        print(inv.read_registers())
