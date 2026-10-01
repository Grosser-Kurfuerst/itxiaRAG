from uuid import UUID

from catalog.management.base import KBCommand
from catalog.management.io import actor_by_name, print_job, write_report
from catalog.presenters import job_report, job_summary
from catalog.selectors import maintenance_job
from contracts.serializers import JobReportSerializer
from contracts.serializers import ReviewSerializer
from catalog.services import review_job
from catalog.management.io import validate_input
from contracts.errors import DomainError
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
        group.add_argument("--review", choices=["approved", "rejected"])
        parser.add_argument("--note")

    def run(self, *args, **options):
        actor = actor_by_name(options["actor"])
        if options["note"] is not None and not options["review"]:
            raise DomainError("INVALID_ARGUMENT", "--note 仅用于人工复核")
        if options["review"]:
            data = validate_input(ReviewSerializer, {"decision": options["review"], "note": options["note"]})
            job = review_job(options["id"], actor=actor, **data)
            self.stdout.write(f"reviewed job_id={job.pk} decision={job.review_status}")
            return
        if options["report"]:
            job = maintenance_job(options["id"], actor)
            write_report(options["report"], JobReportSerializer(job_report(job)).data)
            self.stdout.write(f"report_written job_id={job.pk}")
            return
        job = resume_import(options["id"], actor, retry=options["retry"])
        print_job(self, job_summary(job))
