# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2016 Dong Zhuang, Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from django.core.checks import register, Tags as DjangoTags
from django.conf import settings

from course.latex.utils import get_all_indirect_subclasses
from course.latex.converter import CommandBase


class Tags(DjangoTags):
    relate_course_tag = 'relate_course_tag'


@register(Tags.relate_course_tag, deploy=True)
def latex2image_bin_check(app_configs, **kwargs):
    """
    Check if all tex compiler and image converter
    are correctly configured, if latex utility is
    enabled.
    """
    if not getattr(settings, "RELATE_LATEX_TO_IMAGE_ENABLED", False):
        return []
    klass = get_all_indirect_subclasses(CommandBase)
    instance_list = [cls() for cls in klass]
    errors = []
    for instance in instance_list:
        error = instance.check()
        if error:
            errors.append(error)
    return errors