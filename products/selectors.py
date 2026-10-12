from products.models import ProductSpec


def condition_options(visibilities):
    """可见评测机型的显卡型号与品牌，供推荐请求校验时列出可选值。"""
    specs = ProductSpec.objects.filter(review_context__source__visibility__in=visibilities)
    return {
        "gpus": sorted(set(specs.exclude(gpu=None).values_list("gpu", flat=True))),
        "brands": sorted(set(specs.values_list("brand", flat=True))),
    }
