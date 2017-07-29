# -*- coding: utf-8 -*-
#! /usr/bin/env python3

"""
Generate minified stylesheet for ipython notebook
"""

import sys
import os
import re
from io import BytesIO
from pygments.formatters import get_formatter_by_name
from six.moves.urllib.request import urlopen


NOTEBOOK_CSS_VERSION = '4.3.0'
CSS_URL = ("https://cdn.jupyter.org/notebook/%s/style/style.min.css"
           % NOTEBOOK_CSS_VERSION)
NBCONVERT_CSS_SPLIT="""
/*!
*
* IPython notebook
*
*/"""

ORIGINAL_CSS_HIGHLIGHT_CLASS = ".highlight"
CSS_HIGHLIGHT_CLASS = ".codehilite"
DEFAULT_PYGMENTS_STYLE = "default"

DEST_DIR = (
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            os.path.pardir, 'relate', 'static','css')))
CSS_DEST = os.path.join(DEST_DIR, 'ipynb.style.css')
CSS_MINIFIED_DEST = os.path.join(DEST_DIR, 'ipynb.style.min.css')


class GenerateCSS(object):
    def _download(self):
        try:
            return urlopen(CSS_URL).read()
        except Exception as e:
            if 'ssl' in str(e).lower():
                try:
                    import pycurl
                except ImportError:
                    print(
                        "Failed, try again after installing PycURL with "
                        "`pip install pycurl` to avoid outdated SSL.",
                        file=sys.stderr)
                    raise e
                else:
                    print("Failed, trying again with PycURL to avoid "
                          "outdated SSL.",
                          file=sys.stderr)
                    return self._download_pycurl()
            raise e

    def _download_pycurl(self):
        """Download CSS with pycurl, in case of old SSL (e.g. Python < 2.7.9)."""
        import pycurl
        c = pycurl.Curl()
        c.setopt(c.URL, CSS_URL)
        buf = BytesIO()
        c.setopt(c.WRITEDATA, buf)
        c.perform()
        return buf.getvalue().decode()

    def process_nbconvert_css(self):
        print("Downloading CSS: %s" % CSS_URL)
        try:
            css = self._download()
        except Exception as e:
            msg = "Failed to download css from %s: %s" % (CSS_URL, e)
            print(msg, file=sys.stderr)
            return
        return self._get_ipython_notebook_css(css)

    def _get_ipython_notebook_css(self, css):
        print("Processing CSS: %s" % CSS_URL)
        try:
            nb_css = css.split(NBCONVERT_CSS_SPLIT.encode())[1]
        except IndexError:
            raise ValueError("Bad splitter for notebook css %s"
                             % NBCONVERT_CSS_SPLIT)
        return nb_css.replace(ORIGINAL_CSS_HIGHLIGHT_CLASS.encode(),
                              CSS_HIGHLIGHT_CLASS.encode())

    def process_nbconvert_default_highlight_style_defs(self):
        print("Processing code highlight CSS")
        def get_default_highlight_style_defs():
            formatter = get_formatter_by_name("html", style=DEFAULT_PYGMENTS_STYLE)
            return formatter.get_style_defs()

        style_defs = get_default_highlight_style_defs()
        return (
            "\n".join(["%s %s" % (CSS_HIGHLIGHT_CLASS, line)
                       for line in style_defs.splitlines()]))

    def get_assembled_and_minified_css(self):
        nbcovert_css = self.process_nbconvert_css()
        if not nbcovert_css:
            return

        highlight_css = self.process_nbconvert_default_highlight_style_defs()
        if not highlight_css:
            return

        css = "\n".join([highlight_css, nbcovert_css.decode()])
        minified_css = self.get_minified_css(css)
        return css, minified_css

    def get_minified_css(self, css):
        # copied from https://stackoverflow.com/a/223689/3437454

        # preserve IE<6 comment hack
        css = re.sub(r'\s*/\*\s*\*/', "$$HACK1$$", css)
        css = re.sub(r'/\*[\s\S]*?\*/', "", css)

        # preserve IE<6 comment hack
        css = css.replace("$$HACK1$$", '/**/')

        # url() doesn't need quotes
        css = re.sub(r'url\((["\'])([^)]*)\1\)', r'url(\2)', css)

        # spaces may be safely collapsed as generated content will
        # collapse them anyway
        css = re.sub(r'\s+', ' ', css)

        # shorten collapsable colors: #aabbcc to #abc
        css = re.sub(r'#([0-9a-f])\1([0-9a-f])\2([0-9a-f])\3(\s|;)',
                     r'#\1\2\3\4', css)

        # fragment values can loose zeros
        css = re.sub(r':\s*0(\.\d+([cm]m|e[mx]|in|p[ctx]))\s*;', r':\1;', css)

        result = ""
        for rule in re.findall(r'([^{]+){([^}]*)}', css):

            # we don't need spaces around operators
            selectors = [re.sub(r'(?<=[\[\(>+=])\s+|\s+(?=[=~^$*|>+\]\)])', r'',
                                selector.strip())
                         for selector in rule[0].split(',')]

            # order is important, but we still want to discard repetitions
            properties = {}
            porder = []
            for prop in re.findall('(.*?):(.*?)(;|$)', rule[1]):
                key = prop[0].strip().lower()
                if key not in porder: porder.append(key)
                properties[key] = prop[1].strip()

            # output rule if it contains any declarations
            if properties:
                result += (
                "%s{%s}" % (','.join(selectors), ''.join(
                    ['%s:%s;' % (key, properties[key]) for key in porder])[:-1]))

        return result

    def run(self):
        css, minified_css = self.get_assembled_and_minified_css()

        with open(CSS_DEST, 'wb') as f:
            f.write(css.encode())
        with open(CSS_MINIFIED_DEST, 'wb') as f:
            f.write(minified_css.encode())
        print("Succesfully generated CSS to %s" % DEST_DIR)



def main():
    g = GenerateCSS()
    g.run()


if __name__ == "__main__":
    main()