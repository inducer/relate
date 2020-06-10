from django.core.management.base import BaseCommand, CommandError  # noqa
from course.models import FlowPageVisit
from django.db import transaction


def convert_flow_page_visit(fpv):
    course = fpv.flow_session.participation.course

    from course.content import (
        get_course_repo, get_flow_desc,
        get_flow_page_desc, instantiate_flow_page)
    repo = get_course_repo(course)
    flow_id = fpv.flow_session.flow_id
    commit_sha = course.active_git_commit_sha.encode()
    flow_desc = get_flow_desc(repo, course,
            flow_id, commit_sha)
    page_desc = get_flow_page_desc(
            fpv.flow_session.flow_id, flow_desc,
            fpv.page_data.group_id, fpv.page_data.page_id)
    page = instantiate_flow_page(
            location="flow '%s', group, '%s', page '%s'"
            % (flow_id,
                fpv.page_data.group_id, fpv.page_data.page_id),
            repo=repo, page_desc=page_desc,
            commit_sha=commit_sha)

    from course.page.upload import FileUploadQuestion
    if not isinstance(page, FileUploadQuestion):
        return False

    content, mime_type = page.get_content_from_answer_data(
            fpv.answer)
    from course.page.base import PageContext
    pctx = PageContext(
            course=course,
            repo=repo,
            commit_sha=commit_sha,
            flow_session=fpv.flow_session,
            page_uri=None)

    from django.core.files.base import ContentFile
    answer_data = page.file_to_answer_data(
            pctx, ContentFile(content), mime_type)
    fpv.answer = answer_data
    fpv.save()

    return True


class Command(BaseCommand):
    help = (
            "Migrates file upload submissions out of the database and into "
            "the storage given by RELATE_SUBMISSION_STORAGE. This command may "
            "safely be interrupted and will pick up where it left off.")

    def handle(self, *args, **options):
        count = -1
        total_count = 0
        while count:
            with transaction.atomic():
                count = 0
                for fpv in (FlowPageVisit
                        .objects
                        .filter(answer__contains="base64_data")
                        .select_related(
                            "flow_session",
                            "flow_session__participation",
                            "flow_session__participation__course",
                            "flow_session__participation__user",
                            "page_data")
                        [:200]):

                    if convert_flow_page_visit(fpv):
                        count += 1

                total_count += count
                self.stderr.write("converted %d page visits..." % total_count)

        self.stderr.write("done!")
