from django.core.management.base import BaseCommand, CommandError  # noqa
from course.models import FlowPageVisit
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist


def convert_flow_page_visit(stderr, fpv):
    course = fpv.flow_session.course

    from course.content import (
        get_course_repo, get_flow_desc,
        get_flow_page_desc, instantiate_flow_page)
    repo = get_course_repo(course)
    flow_id = fpv.flow_session.flow_id
    commit_sha = course.active_git_commit_sha.encode()
    try:
        flow_desc = get_flow_desc(repo, course,
                flow_id, commit_sha)
    except ObjectDoesNotExist:
        stderr.write("warning: no flow yaml file found for '%s' in '%s'"
                % (flow_id, course.identifier))
        return

    try:
        page_desc = get_flow_page_desc(
                fpv.flow_session.flow_id, flow_desc,
                fpv.page_data.group_id, fpv.page_data.page_id)
    except ObjectDoesNotExist:
        stderr.write("warning: no page yaml desc found for "
                f"'{flow_id}:{fpv.page_data.group_id}/{fpv.page_data.page_id}' "
                f"in '{course.identifier}'")
        return

    page = instantiate_flow_page(
            location="flow '%s', group, '%s', page '%s'"
            % (flow_id,
                fpv.page_data.group_id, fpv.page_data.page_id),
            repo=repo, page_desc=page_desc,
            commit_sha=commit_sha)

    from course.page.base import PageContext
    pctx = PageContext(
            course=course,
            repo=repo,
            commit_sha=commit_sha,
            flow_session=fpv.flow_session,
            page_uri=None)

    from course.page.upload import FileUploadQuestion
    from course.page.code import CodeQuestion

    if isinstance(page, FileUploadQuestion):
        content, mime_type = page.get_content_from_answer_data(
                fpv.answer)

        from django.core.files.base import ContentFile
        answer_data = page.file_to_answer_data(
                pctx, ContentFile(content), mime_type)
        fpv.answer = answer_data
        fpv.save()

        return True

    elif isinstance(page, CodeQuestion):
        code = page.get_code_from_answer_data(fpv.answer)
        answer_data = page.code_to_answer_data(pctx, code)
        fpv.answer = answer_data
        fpv.save()

        return True
    else:
        return False

    assert False


class Command(BaseCommand):
    help = (
            "Migrates bulk data (e.g. file upload submissions) out of the database "
            "and into the storage given by RELATE_BULK_STORAGE. This command may "
            "safely be interrupted and will pick up where it left off.")

    def handle(self, *args, **options):
        from django.db.models import Q

        total_count = 0
        from django.db.models.functions import Length
        fpv_qset = (FlowPageVisit
                .objects
                .annotate(answer_len=Length("answer"))
                .filter(
                    Q(answer__contains="base64_data")
                    | (
                        # code questions with long answer_data
                        Q(answer__contains="answer")
                        & Q(answer_len__gt=128))
                    )
                .select_related(
                    "flow_session",
                    "flow_session__participation",
                    "flow_session__participation__course",
                    "flow_session__participation__user",
                    "page_data"))

        fpv_qset_iterator = iter(fpv_qset)

        quit = False
        while not quit:
            with transaction.atomic():
                for i in range(200):
                    try:
                        fpv = next(fpv_qset_iterator)
                    except StopIteration:
                        quit = True
                        break

                    if convert_flow_page_visit(self.stderr, fpv):
                        total_count += 1

            self.stdout.write("converted %d page visits..." % total_count)

        self.stdout.write("done!")