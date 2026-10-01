from uuid import UUID

from catalog.management.base import KBCommand
from catalog.management.io import actor_by_name, print_job, read_metadata, read_text, validate_input
from catalog.presenters import job_summary
from contracts.serializers import ImportContentSerializer, SourceImportSerializer
from ingestion.pipeline import import_text


class Command(KBCommand):
    help = "导入一份人工整理短笔记；同步构建，待复核时退出码为 4"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--metadata", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--source", type=UUID)

    def run(self, *args, **options):
        actor = actor_by_name(options["actor"])
        data = read_metadata(options["metadata"])
        data["input_text"] = read_text(options["file"])
        serializer = ImportContentSerializer if options["source"] else SourceImportSerializer
        job, reused = import_text(validate_input(serializer, data), actor, options["source"])
        print_job(self, job_summary(job, reused))
