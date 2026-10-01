from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.authtoken.models import Token

from catalog.accounts import permissions_for
from catalog.management.base import KBCommand
from catalog.models import RetrievalSettings
from catalog.policies import SYSTEM_USERNAME
from catalog.profiles import load_profiles
from contracts.errors import DomainError


class Command(KBCommand):
    help = "受控初始化活动配置和仅用于审计的系统账号"

    def add_arguments(self, parser):
        parser.add_argument("--profiles", default=str(settings.PROFILE_DIR))

    @transaction.atomic
    def run(self, *args, **options):
        profiles = load_profiles(options["profiles"])
        config, _ = RetrievalSettings.objects.get_or_create(pk=1, defaults=profiles)
        config = RetrievalSettings.objects.select_for_update().get(pk=1)
        if any(getattr(config, key) != value for key, value in profiles.items()):
            raise DomainError("PROFILE_CONFLICT", "已有配置不同，初始化不能覆盖，请显式维护升级", 409)
        user, _ = get_user_model().objects.get_or_create(username=SYSTEM_USERNAME)
        user.set_unusable_password()
        user.is_active = True
        user.is_staff = user.is_superuser = False
        user.save()
        user.groups.clear()
        user.user_permissions.set(permissions_for(["read_internal", "maintain_source", "review_import"]))
        Token.objects.filter(user=user).delete()
        self.stdout.write(f"initialized index={config.index_profile_hash} query={config.query_profile_hash}")
