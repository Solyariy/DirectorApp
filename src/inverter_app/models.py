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
    # Per-string PV operating point and the battery charge limit, used to
    # tell curtailed solar readings from unconstrained ones. Nullable for
    # rows recorded before these registers were read.
    pv1_voltage_v = models.FloatField(null=True)
    pv1_current_a = models.FloatField(null=True)
    pv1_power_w = models.IntegerField(null=True)
    pv2_voltage_v = models.FloatField(null=True)
    pv2_current_a = models.FloatField(null=True)
    pv2_power_w = models.IntegerField(null=True)
    battery_max_charge_current_a = models.IntegerField(null=True)
