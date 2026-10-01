from uuid import UUID
from catalog.management.base import KBCommand
from catalog.management.io import actor_by_name, print_job
from catalog.presenters import job_summary
from catalog.services import publish_build


class Command(KBCommand):
    help = "统一发布已批准候选；过时构建或撤回来源不能发布"

    def add_arguments(self, parser):
        parser.add_argument("--id", required=True, type=UUID)
        parser.add_argument("--actor", required=True)

    def run(self, *args, **options):
        job = publish_build(options["id"], actor_by_name(options["actor"]))
        print_job(self, job_summary(job))
