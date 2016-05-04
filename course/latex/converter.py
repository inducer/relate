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

import six
import os
import platform
import sys
import shutil
import re

from django.core.checks import Critical
from django.core.management.base import CommandError
from django.core.exceptions import ImproperlyConfigured
from django.utils.encoding import DEFAULT_LOCALE_ENCODING
from django.utils.translation import ugettext as _, string_concat
from django.conf import settings

from .utils import (
    popen_wrapper, get_basename_or_md5,
    _file_read, _file_write, get_abstract_latex_log)


# {{{ latex compiler classes and image converter classes

class CommandBase(object):
    @property
    def name(self):
        """
        The name of the command tool
        """
        raise NotImplementedError

    @property
    def cmd(self):
        """
        The string of the command
        """
        raise NotImplementedError

    required_version = ""
    bin_path = ""

    def check(self):
        error = ""
        out = ""
        strerror = ""

        try:
            out, err, status = popen_wrapper(
                [self.bin_path, '--version'],
                stdout_encoding=DEFAULT_LOCALE_ENCODING
            )
        except CommandError as e:
            strerror = e.__str__()

        m = re.search(r'(\d+)\.(\d+)\.?(\d+)?', out)
        if not m:
            error = Critical(
                strerror,
                hint=("Unable to run '%(cmd)s'. Is "
                      "%(tool)s installed or has its "
                      "path correctly configured "
                      "in local_settings.py?")
                     % {"cmd": self.cmd,
                        "tool": self.name,
                        },
                obj=self.name
            )
        elif self.required_version:
            version = ".".join(d for d in m.groups() if d)
            from distutils.version import LooseVersion as LV
            if LV(version) < LV(self.required_version):
                error = Critical(
                    "Version outdated",
                    hint=("'%(tool)s' with version "
                          ">=%(required)s is required, "
                          "current version is %(version)s"
                          )
                         % {"tool": self.name,
                            "required": self.required_version,
                            "version": version
                            },
                    obj=self.name
                )
        return error


class TexCompilerBase(CommandBase):
    def __init__(self):
        self.bin_path_dir = getattr(
            settings, "RELATE_%s_BIN_DIR" % self.name.upper(),
            getattr(settings, "RELATE_LATEX_BIN_DIR", "")
        )
        self.bin_path = os.path.join(
            self.bin_path_dir, self.cmd.lower())


class Latexmk(TexCompilerBase):
    name = "latexmk"
    cmd = "latexmk"
    required_version = "4.39"


class LatexCompiler(TexCompilerBase):
    latexmk_option = (
        '-latexoption="-no-shell-escape '
        '-interaction=batchmode -halt-on-error "'
    )

    @property
    def output_format(self):
        raise NotImplementedError()

    def __init__(self):
        super(LatexCompiler, self).__init__()
        self.latexmk_prog_repl = self._get_latexmk_prog_repl()

    def _get_latexmk_prog_repl(self):
        """
        Program replace when using "-pdflatex=" or "-latex="
        arg in latexmk, especially needed when compilers are
        not in system's default $PATH.
        :return: the latexmk arg "-pdflatex=/path/to/pdflatex" for
        # pdflatex or "-pdflatex=/path/to/xelatex" for xelatex
        """
        return (
            "-%s=%s" % (self.name.lower(), self.bin_path.lower())
        )

    def get_latexmk_subpro_cmdline(self, input_path):
        latexmk = Latexmk()
        return [
            latexmk.bin_path,
            "-%s" % self.output_format,
            self.latexmk_prog_repl,
            self.latexmk_option,
            input_path
        ]


class Latex(LatexCompiler):
    name = "latex"
    cmd = "latex"
    output_format = "dvi"


class PdfLatex(LatexCompiler):
    name = "PdfLatex"
    cmd = "pdflatex"
    output_format = "pdf"


class LuaLatex(LatexCompiler):
    name = "LuaLatex"
    cmd = "lualatex"
    output_format = "pdf"
    def __init__(self):
        super(LuaLatex, self).__init__()
        self.latexmk_prog_repl = (
            "-%s=%s" % ("pdflatex", self.bin_path)
        )


class XeLatex(LatexCompiler):
    name = "XeLatex"
    cmd = "xelatex"
    output_format = "pdf"
    def __init__(self):
        super(XeLatex, self).__init__()
        self.latexmk_prog_repl = (
            "-%s=%s" % ("pdflatex", self.bin_path)
        )


class Imageconverter(CommandBase):

    @property
    def output_format(self):
        raise NotImplementedError

    def __init__(self):
        bin_path_dir = getattr(
            settings, "RELATE_%s_BIN_DIR" % self.name.upper(),
            ""
        )
        self.bin_path = os.path.join(bin_path_dir,
                                     self.cmd.lower())

    def get_converter_cmdline(
            self, input_filepath, output_filepath):
        raise NotImplementedError


class Dvipng(TexCompilerBase, Imageconverter):
    # Inheritate TexCompilerBase's bin_path
    # since dvipng is usually installed in
    # latex compilers' bin dir.
    name = "dvipng"
    cmd = "dvipng"
    output_format = "png"
    def get_converter_cmdline(
            self, input_filepath, output_filepath):
        return [self.bin_path,
                '-o', output_filepath,
                '-pp', '1',
                '-T', 'tight',
                '-z9',
                input_filepath]


class Dvisvg(TexCompilerBase, Imageconverter):
    # Inheritate TexCompilerBase's bin_path
    # since dvisvgm is usually installed in
    # latex compilers' bin dir.
    name = "dvisvg"
    cmd = "dvisvgm"
    output_format = "svg"
    def get_converter_cmdline(
            self, input_filepath, output_filepath):
        return[self.bin_path,
            '--no-fonts',
            '-o', output_filepath,
            input_filepath]


class ImageMagick(Imageconverter):
    name = "ImageMagick"
    cmd = "convert"
    output_format = "png"

    def get_converter_cmdline(
            self, input_filepath, output_filepath):
        return [self.bin_path,
                '-density', '96',
                '-quality', '85',
                '-trim',
                input_filepath,
                output_filepath
                ]

# }}}


# {{{ convert file to data uri

def get_file_data_uri(file_path):
    """
    Convert file to data URI
    """
    if not file_path:
        return None

    try:
        buf = _file_read(file_path)
    except OSError:
        raise

    from mimetypes import guess_type
    mime_type = guess_type(file_path)[0]

    from base64 import b64encode
    return "data:%(mime_type)s;base64,%(b64)s" % {
        "mime_type": mime_type,
        "b64": b64encode(buf).decode(),
    }

# }}}


# {{{ Base tex2img class

class Tex2ImgBase(object):
    """The abstract class of converting tex source to images.
    """

    @property
    def compiler(self):
        """
        :return: an instance of `LatexCompiler`
        """
        raise NotImplementedError()

    @property
    def converter(self):
        """
        :return: an instance of `Imageconverter`
        """
        raise NotImplementedError()

    def __init__(self, tex_source, tex_filename, output_dir):
        """
        :param tex_source: Required, a string representing the
        full tex source code.
        :param tex_filename: Optional, a string
        :param output_dir: Required, a string of the path where
        the images and error logs will be saved.
        """

        if tex_source:
            tex_source = tex_source.strip()
        if not tex_source:
            raise ValueError(
                _("Param 'tex_source' can not be an empty string")
            )
        assert isinstance(tex_source, unicode)
        self.tex_source = tex_source

        if output_dir:
            output_dir = output_dir.strip()
        if not output_dir:
            raise ValueError(
                _("Param output_dir must be specified"))
        else:
            try:
                if (not os.path.exists(output_dir)
                        or not os.path.isdir(output_dir)):
                    os.makedirs(output_dir)
            except Exception:
                raise ValueError(
                    _("Param output_dir '%s' is not a valid path")
                    % output_dir)

        self.working_dir = None

        self.basename = get_basename_or_md5(
            tex_filename, tex_source)

        self.image_format = self.converter.output_format \
            .replace(".", "").lower()
        self.image_ext = ".%s" % self.image_format

        self.compiled_ext =".%s" % self.compiler.output_format\
            .replace(".", "").lower()

        # Where the latex compilation error log
        # will finally be saved.
        self.errlog_saving_path = os.path.join(
            output_dir,
            "%s_%s.log" % (self.basename, self.compiler.cmd)
        )

        # Where the generated image will finally be saved.
        self.image_saving_path = os.path.join(
            output_dir,
            "%s_%s.%s" % (self.basename,
                          self.compiler.cmd,
                          self.image_format)
        )

    def get_compiler_cmdline(self, tex_path):
        return self.compiler.get_latexmk_subpro_cmdline(tex_path)

    def get_converter_cmdline(self, input_path, output_path):
        return self.converter.get_converter_cmdline(
            input_path, output_path)

    def _remove_working_dir(self):
        shutil.rmtree(self.working_dir)

    def get_compiled_file(self):
        """
        Compile latex source. If failed, error log will copied
        to ``output_dir``.
        :return: string, the path of the compiled file if succeeded.
        """
        from tempfile import mkdtemp
        self.working_dir = mkdtemp(prefix="RELATE_LATEX_")

        tex_filename = self.basename + ".tex"
        tex_path = os.path.join(self.working_dir, tex_filename)
        _file_write(tex_path, self.tex_source.encode('UTF-8'))

        log_path = tex_path.replace(".tex", ".log")
        compiled_file_path = tex_path.replace(
            ".tex", self.compiled_ext)

        cmdline = self.get_compiler_cmdline(tex_path)
        output, error, status = popen_wrapper(
            cmdline, cwd=self.working_dir)

        if status != 0:
            try:
                log = _file_read(log_path)
            except OSError:
                # no log file is generated
                self._remove_working_dir()
                raise RuntimeError(error)

            try:
                log = get_abstract_latex_log(log)
                _file_write(self.errlog_saving_path, log)
            except:
                raise
            finally:
                self._remove_working_dir()
                from django.utils.html import escape
                raise ValueError(
                    "<pre>%s</pre>" % escape(log).strip())

        if os.path.isfile(compiled_file_path):
            return compiled_file_path
        else:
            self._remove_working_dir()
            raise RuntimeError(
                string_concat(
                    "%s." % error,
                    _('No %s file was produced.')
                    % self.compiler.output_format)
            )

    def get_converted_image(self):
        """
        Convert compiled file into image. If succeeded, the image
        will be copied to ``output_dir``.
        :return: string, the path of the generated image
        """
        compiled_file_path = self.get_compiled_file()
        if not compiled_file_path:
            return None
        image_path = compiled_file_path.replace(
            self.compiled_ext,
            self.image_ext)

        cmdline = self.get_converter_cmdline(
            compiled_file_path, image_path)

        output, error, status = popen_wrapper(
            cmdline,
            cwd=self.working_dir
        )

        if status != 0:
            self._remove_working_dir()
            raise RuntimeError(error)

        n_images = get_number_of_images(image_path, self.image_ext)
        if n_images == 0:
            raise ValueError(
                _("No image was generated."))
        elif n_images > 1:
            raise ValueError(
                string_concat(
                    "%s images are generated while expecting 1, "
                    "possibly due to long pdf file."
                    % (n_images, )
                ))

        try:
            shutil.copyfile(image_path, self.image_saving_path)
        except OSError:
            raise RuntimeError(error)
        finally:
            self._remove_working_dir()

        return self.image_saving_path

    def get_compile_err_cached(self):
        """
        If the problematic latex source is not modified, check
        wheter there is error log both in cache and output_dir.
        If it exists, raise the error.
        :return: None if no error log find.
        """
        err_result = None

        try:
            import django.core.cache as cache
        except ImproperlyConfigured:
            err_cache_key = None
        else:
            def_cache = cache.caches["default"]
            err_cache_key = ("latex_err:%s:%s"
                             % (self.compiler.cmd, self.basename))
            # Memcache is apparently limited to 250 characters.
            if len(err_cache_key) < 240:
                err_result = def_cache.get(err_cache_key)
            if err_result is not None:
                assert isinstance(err_result, six.string_types),\
                    err_cache_key

        if err_result is None:
            # read the saved err_log if it exists
            if os.path.isfile(self.errlog_saving_path):
                err_result = _file_read(self.errlog_saving_path)
                assert isinstance(err_result, six.string_types)

        if err_result:
            if err_cache_key:
                if len(err_result) <= getattr(
                        settings, "RELATE_CACHE_MAX_BYTES", 0):
                        def_cache.add(err_cache_key, err_result, None)

            from django.utils.html import escape
            raise ValueError(
                "<pre>%s</pre>" % escape(err_result).strip())

        return None

    def get_data_uri_cached(self, force_regenerate=False):
        """
        :param force_regenerate: :class:`Bool', if True, the tex file
        will be recompiled and re-convert the image, regardless of
        existing file or cached result.
        :return: string, data uri of the coverted image.
        """
        uri_result = None
        if force_regenerate:
            image_path = self.get_converted_image()
            uri_result = get_file_data_uri(image_path)
            assert isinstance(uri_result, six.string_types)

        if not uri_result:
            err_result = self.get_compile_err_cached()
            if err_result:
                return None

        try:
            import django.core.cache as cache
        except ImproperlyConfigured:
            uri_cache_key = None
        else:
            def_cache = cache.caches["default"]

            from hashlib import md5
            uri_cache_key = (
                "latex2img:%s:%s" % (
                    self.compiler.cmd,
                    md5(
                        self.image_saving_path.encode("utf-8")
                    ).hexdigest()
                )
            )
            if not uri_result:
                # Memcache is apparently limited to 250 characters.
                if len(uri_cache_key) < 240:
                    uri_result = def_cache.get(uri_cache_key)
                    if uri_result:
                        assert isinstance(
                            uri_result, six.string_types),\
                            uri_cache_key
                        return uri_result

        # Neighter regenerated nor cached,
        # then read or generate the image
        if not uri_result:
            if not os.path.isfile(self.image_saving_path):
                self.image_saving_path = self.get_converted_image()
            uri_result = get_file_data_uri(self.image_saving_path)
            assert isinstance(uri_result, six.string_types)

        assert uri_result

        # no cache configured
        if not uri_cache_key:
            return uri_result

        # cache configure, but image not cached
        allowed_max_bytes = getattr(
            settings, "RELATE_IMAGECACHE_MAX_BYTES",
            getattr(
                settings, "RELATE_CACHE_MAX_BYTES",
            )
        )
        if len(uri_result) <= allowed_max_bytes:
            # image size larger than allowed_max_bytes
            # won't be cached, espeically for svgs.
            def_cache.add(uri_cache_key, uri_result, None)
        return uri_result

# }}}


# {{{ derived tex2img converter

class Latex2Svg(Tex2ImgBase):
    compiler = Latex()
    converter = Dvisvg()


class Lualatex2Png(Tex2ImgBase):
    compiler = LuaLatex()
    converter = ImageMagick()


class Latex2Png(Tex2ImgBase):
    compiler = Latex()
    converter = Dvipng()


class Pdflatex2Png(Tex2ImgBase):
    compiler = PdfLatex()
    converter = ImageMagick()


class Xelatex2Png(Tex2ImgBase):
    compiler = XeLatex()
    converter = ImageMagick()

# }}}


# {{{ get tex2img class

ALLOWED_COMPILER = ['latex', 'pdflatex', 'xelatex', 'lualatex']
ALLOWED_LATEX2IMG_FORMAT = ['png', 'svg']
ALLOWED_COMPILER_FORMAT_COMBINATION = (
    ("latex", "png"),
    ("latex", "svg"),
    ("lualatex", "png"),
    ("pdflatex", "png"),
    ("xelatex", "png")
)


def get_tex2img_class(compiler, image_format):
    image_format = image_format.replace(".", "").lower()
    compiler = compiler.lower()
    if not image_format in ALLOWED_LATEX2IMG_FORMAT:
        raise ValueError(
            _("Unsupported image format '%s'") % image_format)

    if not compiler in ALLOWED_COMPILER:
        raise ValueError(
            _("Unsupported tex compiler '%s'") % compiler)

    if not (compiler, image_format) in ALLOWED_COMPILER_FORMAT_COMBINATION:
        raise ValueError(
            _("Unsupported combination: "
              "('%(compiler)s', '%(format)s'). "
              "Currently support %(supported)s.")
              % {"compiler": compiler,
                 "format": image_format,
                 "supported": ", ".join(
                     str(e) for e in ALLOWED_COMPILER_FORMAT_COMBINATION)}
        )

    class_name = "%s2%s" % (compiler.title(), image_format.title())

    return getattr(sys.modules[__name__], class_name)

# }}}

# {{{ check if multiple images are generated due to long pdf

def get_number_of_images(image_path, image_ext):
    if os.path.isfile(image_path):
        return 1
    count = 0
    while True:
        try_path = (
            "%(image_path)s-%(number)d%(ext)s"
            % {"image_path": image_path.replace(image_ext, ""),
               "number": count,
               "ext": image_ext
               }
        )
        if not os.path.isfile(try_path):
            break
        count += 1

    return count

# }}}

# vim: foldmethod=marker
