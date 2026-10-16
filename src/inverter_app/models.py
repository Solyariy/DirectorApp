from django.db import models


class EnergySnapshot(models.Model):
    timestamp = models.DateTimeField(auto_created=True)
    solar_power_w = models.IntegerField()
    load_power_w = models.IntegerField()
    grid_power_w = models.IntegerField()
    battery_power_w = models.IntegerField()
    battery_charge_pct = models.IntegerField()
    battery_voltage_v = models.FloatField()
    grid_voltage_v = models.FloatField()
