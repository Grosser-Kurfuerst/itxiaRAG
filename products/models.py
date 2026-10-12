from django.db import models

from catalog.models import ContextUnit


class ProductSpec(models.Model):
    """一台评测过的具体配置。源头是 products/specs/ 下的规格文件，库中记录由 import_specs 派生。

    空值表示“未知”，不表示“没有”；枚举取值与字段口径见 contracts/products.py 与机型规格库方案 5.1 节。
    """

    key = models.CharField(max_length=200, unique=True)
    brand = models.CharField(max_length=50)
    review_context = models.OneToOneField(
        ContextUnit, null=True, on_delete=models.SET_NULL, related_name="product_spec")
    price_cny = models.FloatField(null=True)
    price_kind = models.CharField(max_length=16, null=True)
    price_date = models.DateField(null=True)
    weight_kg = models.FloatField(null=True)
    screen_inch = models.FloatField(null=True)
    panel = models.CharField(max_length=16, null=True)
    cpu = models.CharField(max_length=100, null=True)
    has_dgpu = models.BooleanField(null=True)
    gpu = models.CharField(max_length=50, null=True)
    ram_gb = models.PositiveIntegerField(null=True)
    ram_upgradable = models.CharField(max_length=16, null=True)
    storage_gb = models.PositiveIntegerField(null=True)
    battery_hours = models.FloatField(null=True)
    is_gaming = models.BooleanField(null=True)
    ports = models.JSONField(default=dict)
    ports_text = models.TextField(blank=True, default="")
    extra = models.JSONField(default=dict)
    evidence = models.JSONField(default=dict)
    note = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "product_spec"
        ordering = ["key"]
