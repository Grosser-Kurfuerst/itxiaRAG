from uuid import UUID

from catalog.management.base import KBCommand
from catalog.management.io import actor_by_name, print_job, write_report
from catalog.presenters import job_report, job_summary
from catalog.selectors import maintenance_job
from contracts.serializers import JobReportSerializer
from ingestion.pipeline import resume_import


class Command(KBCommand):
    help = "查看报告或恢复／显式重试同步任务"

    def add_arguments(self, parser):
        parser.add_argument("--id", required=True, type=UUID)
        parser.add_argument("--actor", required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--report")
        group.add_argument("--resume", action="store_true")
        group.add_argument("--retry", action="store_true")

    def run(self, *args, **options):
        actor = actor_by_name(options["actor"])
        if options["report"]:
            job = maintenance_job(options["id"], actor)
            write_report(options["report"], JobReportSerializer(job_report(job)).data)
            self.stdout.write(f"report_written job_id={job.pk}")
            return
        job = resume_import(options["id"], actor, retry=options["retry"])
        print_job(self, job_summary(job))
