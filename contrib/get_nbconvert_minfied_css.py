# -*- coding: utf-8 -*-
#! /usr/bin/env python3

"""
Generate minified stylesheet for ipython notebook
"""

import os

NOTEBOOK_CSS_VERSION = '4.3.0'
CSS_URL = ("https://cdn.jupyter.org/notebook/%s/style/style.min.css"
           % NOTEBOOK_CSS_VERSION)

REQUEST_TIMEOUT = 6
REQUEST_MAX_RETRIES = 5

IPYTHON_NOTEBOOK_DECLARE_STR = """
/*!
*
* IPython notebook
*
*/"""

IPYTHON_NOTEBOOK_WEBAPP_DECLARE_STR = """
/*!
*
* IPython notebook webapp
*
*/
"""

ORIGINAL_CSS_HIGHLIGHT_CLASS = ".highlight"
CSS_HIGHLIGHT_CLASS = ".codehilite"
PYGMENTS_STYLE = "default"

HIGHLIGT_DECLARE_STR = """
/*!
*
* Pygments "%s" style with "%s" css_class
*
*/
""" %(PYGMENTS_STYLE, CSS_HIGHLIGHT_CLASS)

DEST_DIR = (
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            os.path.pardir, 'relate', 'static', 'css')))

CSS_DEST = os.path.join(DEST_DIR, 'ipynb.style.css')
CSS_MINIFIED_DEST = os.path.join(DEST_DIR, 'ipynb.style.min.css')


def retry_urlopen(request, timeout=REQUEST_TIMEOUT, n_retries=REQUEST_MAX_RETRIES):
    from six.moves.urllib.request import urlopen
    i = 0
    while True:
        try:
            result =  urlopen(request, timeout=timeout).read()
            return result
        except Exception as e:
            from six.moves.urllib.error import URLError
            from socket import timeout as TimeoutError
            if not isinstance(e, (URLError, TimeoutError)):
                raise e
            if not "timed out" in str(e).lower():
                raise e
            i += 1
            if i > n_retries:
                raise e
            print("\rRequest timed out, retry (%s/%s). " % (
                i, n_retries), flush=True, end="")
            import time
            time.sleep(0.1)


def minify_css(css_string):
    url = 'https://cssminifier.com/raw'
    post_fields = {'input': css_string}
    from six.moves.urllib.parse import urlencode
    from six.moves.urllib.request import Request
    request = Request(url, urlencode(post_fields).encode())
    return retry_urlopen(request)


class GenerateCSS(object):
    def _download(self):
        try:
            return retry_urlopen(CSS_URL)
        except Exception as e:
            if 'ssl' in str(e).lower():
                import sys
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
        from io import BytesIO
        buf = BytesIO()
        c.setopt(c.WRITEDATA, buf)
        c.perform()
        return buf.getvalue().decode()

    def process_nbconvert_css(self):
        print("Downloading ipython notebook CSS: %s." % CSS_URL)
        try:
            css = self._download()
            print("Done.")
            return self._process_nbconvert_css(css)
        except:
            raise

    def _process_nbconvert_css(self, css):
        print("Processing downloaded ipython notebook CSS.")
        try:
            css = css.split(IPYTHON_NOTEBOOK_DECLARE_STR.encode())[1]
            css = IPYTHON_NOTEBOOK_DECLARE_STR.encode() + css
        except IndexError:
            raise ValueError("Bad splitter for notebook css %s"
                             % IPYTHON_NOTEBOOK_DECLARE_STR)
        print("Done.")
        return css.replace(ORIGINAL_CSS_HIGHLIGHT_CLASS.encode() + b" ",
                              CSS_HIGHLIGHT_CLASS.encode() + b" ")

    def process_highlight_style_defs(self, style=PYGMENTS_STYLE):
        print("Processing Pygments code highlight CSS.")
        def get_highlight_style_defs():
            from pygments.formatters import get_formatter_by_name
            formatter = get_formatter_by_name("html", style=style)
            return formatter.get_style_defs()

        style_defs = get_highlight_style_defs()
        print("Done.")
        return (HIGHLIGT_DECLARE_STR +
            "\n".join(["%s %s" % (CSS_HIGHLIGHT_CLASS, line)
                       for line in style_defs.splitlines()]))

    def get_assembled_css(self):
        try:
            nbcovert_css = self.process_nbconvert_css()
            highlight_css = self.process_highlight_style_defs()
        except:
            raise
        css = "\n".join([nbcovert_css.decode(), highlight_css])
        print("CSS assembled.")
        return css

    def get_minified_css(self, css):
        css = (css.replace(IPYTHON_NOTEBOOK_DECLARE_STR, "")
               .replace(IPYTHON_NOTEBOOK_WEBAPP_DECLARE_STR, "")
               .replace(HIGHLIGT_DECLARE_STR, "")
               )
        return minify_css(css)

    def run(self):
        css = self.get_assembled_css()
        with open(CSS_DEST, 'wb') as f:
            f.write(css.encode())
        print("Succesfully generated %s" % CSS_DEST)

        print("Minifying CSS...")
        minified_css = self.get_minified_css(css).decode()
        print("Done.")

        with open(CSS_MINIFIED_DEST, 'wb') as f:
            f.write(minified_css.encode())
        print("Succesfully generated %s" % CSS_MINIFIED_DEST)


def main():
    g = GenerateCSS()
    g.run()


if __name__ == "__main__":
    main()
